"""Tests for the behaviour this fork changed against the core integration.

Each test names the defect or rule it guards; docs/decisions.md carries the
reasoning.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_SHUFFLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_SOUND_MODE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_CLEAR_PLAYLIST,
    SERVICE_PLAY_MEDIA,
    SERVICE_SELECT_SOUND_MODE,
    SERVICE_SELECT_SOURCE,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ENTITY_ID,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    SERVICE_SHUFFLE_SET,
    SERVICE_VOLUME_SET,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from music_assistant_client.exceptions import CannotConnect
from music_assistant_models.enums import IdentifierType, MediaType
from music_assistant_models.errors import MusicAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.music_assistant.const import (
    ATTR_ALBUM_TYPE,
    ATTR_MEDIA_ID,
    ATTR_MEDIA_TYPE,
    ATTR_SOURCE_PLAYER,
    DOMAIN,
)
from custom_components.music_assistant.entity import player_configuration_url
from custom_components.music_assistant.media_browser import uri_media_type
from custom_components.music_assistant.services import (
    SERVICE_GET_LIBRARY,
    SERVICE_TRANSFER_QUEUE,
)

from .common import create_players_from_fixture, setup_integration_from_fixtures

ENTITY_ID = "media_player.test_player_1"
PLAYER_ID = "00:00:00:00:00:01"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("library://artist/127", MediaType.ARTIST),
        ("spotify://playlist/artist-mix", MediaType.PLAYLIST),
        ("tidal--Ah76MuMg://track/77616130", MediaType.TRACK),
        ("library://bogus/1", None),
        ("artists", None),
        ("http://example.invalid/stream.mp3", None),
        ("media-source://media_source/local/artist.mp3", None),
    ],
)
def test_uri_media_type(uri: str, expected: MediaType | None) -> None:
    """The media type comes from the uri structure, not from a substring."""
    assert uri_media_type(uri) is expected


async def test_browse_playlist_named_like_an_artist(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A playlist uri containing the word artist browses as a playlist."""
    from custom_components.music_assistant.media_browser import async_browse_media

    await setup_integration_from_fixtures(hass, music_assistant_client)
    playlist = (await music_assistant_client.music.get_library_playlists())[0]
    music_assistant_client.music.get_item_by_uri = AsyncMock(return_value=playlist)

    browse_item = await async_browse_media(
        hass, music_assistant_client, "spotify://playlist/artist-mix", "playlist"
    )

    assert browse_item.media_content_id == playlist.uri
    music_assistant_client.music.get_playlist_tracks.assert_awaited_once()


async def test_volume_set_rounds_to_nearest_percent(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """0.29 becomes 29, not 28 (int() truncated the float product)."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_VOLUME_LEVEL: 0.29},
        blocking=True,
    )
    assert music_assistant_client.send_command.call_args == call(
        "players/cmd/volume_set", player_id=PLAYER_ID, volume_level=29
    )


async def test_play_media_without_extra(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A direct entity call without the extra mapping does not raise KeyError."""
    music_assistant_client.server_info.schema_version = 33
    music_assistant_client.music.verify_item_uri = AsyncMock(return_value=True)
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    entity = next(
        entity
        for entity in hass.data["entity_components"][MEDIA_PLAYER_DOMAIN].entities
        if entity.entity_id == ENTITY_ID
    )
    assert config_entry.state is ConfigEntryState.LOADED

    await entity.async_play_media("music", "spotify://track/1234")

    assert music_assistant_client.send_command.call_args.args == (
        "player_queues/play_media",
    )


async def test_play_media_service_still_passes_extra(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """The media_player.play_media service path keeps working after the change."""
    music_assistant_client.server_info.schema_version = 33
    music_assistant_client.music.verify_item_uri = AsyncMock(return_value=True)
    await setup_integration_from_fixtures(hass, music_assistant_client)
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_MEDIA_CONTENT_ID: "spotify://track/1234",
            ATTR_MEDIA_CONTENT_TYPE: "music",
        },
        blocking=True,
    )
    assert music_assistant_client.send_command.call_args.kwargs["radio_mode"] is False


async def test_queue_actions_raise_without_active_queue(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Shuffle and clear playlist raise a translated error instead of doing nothing."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    player = music_assistant_client.players.get(PLAYER_ID)
    player.active_source = None

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SHUFFLE_SET,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_SHUFFLE: True},
            blocking=True,
        )
    assert err.value.translation_key == "no_active_queue"

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_CLEAR_PLAYLIST,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )
    assert err.value.translation_key == "no_active_queue"
    assert music_assistant_client.send_command.call_count == 0


async def test_source_and_sound_mode_errors_are_translated(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Unknown source and sound mode names raise translated validation errors."""
    await setup_integration_from_fixtures(hass, music_assistant_client)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SELECT_SOURCE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_INPUT_SOURCE: "Nope"},
            blocking=True,
        )
    assert err.value.translation_key == "source_not_found"
    assert err.value.translation_placeholders == {
        "source": "Nope",
        "player": "Test Player 1",
    }

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SELECT_SOUND_MODE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_SOUND_MODE: "Nope"},
            blocking=True,
        )
    assert err.value.translation_key == "sound_mode_not_found"


async def test_server_errors_are_translated(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A server side error surfaces as a translated HomeAssistantError."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.send_command = AsyncMock(
        side_effect=MusicAssistantError("boom")
    )
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_VOLUME_SET,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_VOLUME_LEVEL: 0.5},
            blocking=True,
        )
    assert err.value.translation_key == "server_error"
    assert err.value.translation_placeholders == {"error": "boom"}


async def test_transfer_queue_rejects_foreign_entity(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """An entity of another integration is rejected rather than sent to the server."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    hass.states.async_set("media_player.other", "idle")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_TRANSFER_QUEUE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_SOURCE_PLAYER: "media_player.other"},
            blocking=True,
        )
    assert err.value.translation_key == "entity_not_music_assistant"
    assert music_assistant_client.send_command.call_count == 0


async def test_get_library_validates_album_type(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """album_type accepts AlbumType values and rejects anything else."""
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_LIBRARY,
        {
            ATTR_CONFIG_ENTRY_ID: config_entry.entry_id,
            ATTR_MEDIA_TYPE: "album",
            ATTR_ALBUM_TYPE: ["live", "soundtrack"],
        },
        blocking=True,
        return_response=True,
    )
    assert music_assistant_client.music.get_library_albums.call_args.kwargs[
        "album_types"
    ] == ["live", "soundtrack"]

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_LIBRARY,
            {
                ATTR_CONFIG_ENTRY_ID: config_entry.entry_id,
                ATTR_MEDIA_TYPE: "album",
                ATTR_ALBUM_TYPE: ["mixtape"],
            },
            blocking=True,
            return_response=True,
        )


async def test_get_library_unsupported_media_type(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A media type the library cannot list raises a translated error."""
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_LIBRARY,
            {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_MEDIA_TYPE: "genre"},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "unsupported_media_type"


async def test_service_on_unknown_entry_is_translated(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A config entry id that does not exist raises a translated error."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_LIBRARY,
            {ATTR_CONFIG_ENTRY_ID: "nope", ATTR_MEDIA_TYPE: "album"},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "entry_not_found"


async def test_device_info_uses_browser_reachable_url(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """The configuration URL comes from the server's external address."""
    music_assistant_client.server_url = "http://addon-music-assistant:8094"
    music_assistant_client.server_info.external_url = "https://music.example.invalid"
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, PLAYER_ID), config_entry.entry_id
    )
    assert device is not None
    assert device.configuration_url == (
        f"https://music.example.invalid/#/settings/editplayer/{PLAYER_ID}"
    )
    assert config_entry.state is ConfigEntryState.LOADED

    music_assistant_client.server_info.external_url = None
    music_assistant_client.server_info.base_url = None
    assert player_configuration_url(music_assistant_client, "x").startswith(
        "http://addon-music-assistant:8094/#/"
    )


async def test_device_info_carries_hardware_identifiers(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """MAC, serial, model id and firmware from the server land on the device."""
    players = create_players_from_fixture()
    player = next(player for player in players if player.player_id == PLAYER_ID)
    player.device_info.identifiers = {
        IdentifierType.MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        IdentifierType.SERIAL_NUMBER: "SN123",
    }
    player.device_info.model_id = "X1"
    player.device_info.software_version = "1.2.3"
    with patch("tests.common.create_players_from_fixture", return_value=players):
        config_entry = await setup_integration_from_fixtures(
            hass, music_assistant_client
        )

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, PLAYER_ID), config_entry.entry_id
    )
    assert device is not None
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff") in device.connections
    assert device.serial_number == "SN123"
    assert device.model_id == "X1"
    assert device.sw_version == "1.2.3"


async def test_connection_lost_and_restored_logged_once(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The loss of the server is logged once and its return once."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Music Assistant",
        data={CONF_URL: "http://localhost:8095", CONF_TOKEN: "token"},
        unique_id="1234",
    )
    config_entry.add_to_hass(hass)
    music_assistant_client.connect.side_effect = CannotConnect("down")

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert caplog.text.count("Connection to Music Assistant server") == 1
    assert "lost: down" in caplog.text

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert caplog.text.count("Connection to Music Assistant server") == 1

    music_assistant_client.connect.side_effect = None
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert "restored" in caplog.text
    assert caplog.text.count("Connection to Music Assistant server") == 2


async def test_setup_uses_verify_ssl_from_entry(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """The client session honours the stored verify_ssl choice; old entries stay lax."""
    for stored, expected in ((True, True), (None, False)):
        data = {CONF_URL: "https://localhost:8095"}
        if stored is not None:
            data[CONF_VERIFY_SSL] = stored
        config_entry = MockConfigEntry(
            domain=DOMAIN, data=data, unique_id=f"srv-{stored}"
        )
        config_entry.add_to_hass(hass)
        with patch(
            "custom_components.music_assistant.async_get_clientsession"
        ) as get_session:
            await hass.config_entries.async_setup(config_entry.entry_id)
            await hass.async_block_till_done()
        get_session.assert_called_once_with(hass, verify_ssl=expected)
        await hass.config_entries.async_unload(config_entry.entry_id)


async def test_remove_device_when_entry_not_loaded(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Device removal on an unloaded entry is refused, not an exception."""
    from custom_components.music_assistant import async_remove_config_entry_device

    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, PLAYER_ID), config_entry.entry_id
    )
    assert device is not None
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_play_media_resolution_failure_is_translated(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A media id nothing resolves raises the media_not_found error."""
    from custom_components.music_assistant.services import SERVICE_PLAY_MEDIA_ADVANCED

    music_assistant_client.server_info.schema_version = 33
    music_assistant_client.music.verify_item_uri = AsyncMock(return_value=False)
    music_assistant_client.music.get_item_by_name = AsyncMock(return_value=None)
    await setup_integration_from_fixtures(hass, music_assistant_client)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_PLAY_MEDIA_ADVANCED,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_ID: "nothing here"},
            blocking=True,
        )
    assert err.value.translation_key == "media_not_found"
