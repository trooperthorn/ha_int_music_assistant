"""Regression tests for the core issues and feature requests this fork addressed.

Numbers refer to home-assistant/core issues and home-assistant/feature-requests
discussions; docs/upstream_findings.md carries the analysis.
"""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaClass,
    MediaPlayerState,
    SearchMediaQuery,
)
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from music_assistant_models.enums import EventType, IdentifierType, ProviderType
from music_assistant_models.provider import ProviderInstance
import pytest

from custom_components.music_assistant.const import (
    ATTR_MEDIA_ID,
    ATTR_MEDIA_TYPES,
    ATTR_PROVIDERS,
    ATTR_SEARCH_NAME,
    DOMAIN,
)
from custom_components.music_assistant.media_browser import (
    LIBRARY_RADIO,
    async_browse_media,
    async_search_media,
)
from custom_components.music_assistant.services import (
    SERVICE_GET_PROVIDERS,
    SERVICE_PLAY_MEDIA_ADVANCED,
    SERVICE_SEARCH,
    SERVICE_SYNC_LIBRARY,
)

from .common import (
    create_players_from_fixture,
    setup_integration_from_fixtures,
    trigger_subscription_callback,
)

ENTITY_ID = "media_player.test_player_1"
PLAYER_ID = "00:00:00:00:00:01"


async def test_play_media_targets_the_players_own_queue(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """core#179724: a captured member is addressed itself, not its group leader."""
    music_assistant_client.server_info.schema_version = 33
    music_assistant_client.music.verify_item_uri = AsyncMock(return_value=True)
    await setup_integration_from_fixtures(hass, music_assistant_client)
    player = music_assistant_client.players.get(PLAYER_ID)
    player.active_source = "test_group_player_1"
    player.active_group = "test_group_player_1"
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_UPDATED, PLAYER_ID
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_PLAY_MEDIA_ADVANCED,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_MEDIA_ID: "spotify://track/1234"},
        blocking=True,
    )
    call = music_assistant_client.send_command.call_args
    assert call.args == ("player_queues/play_media",)
    assert call.kwargs["queue_id"] == PLAYER_ID


async def test_player_without_power_concept_follows_playback(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """core#179255: powered None (power control set to none) is not off."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    player = music_assistant_client.players.get(PLAYER_ID)
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.OFF

    player.powered = None
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_UPDATED, PLAYER_ID
    )
    assert hass.states.get(ENTITY_ID).state == player.playback_state.value

    player.powered = False
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_UPDATED, PLAYER_ID
    )
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.OFF


async def test_radio_listing_uses_channel_class(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """core#179557: radio stations are browsable and searchable as channels."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    listing = await async_browse_media(
        hass, music_assistant_client, LIBRARY_RADIO, DOMAIN
    )
    assert listing.children_media_class == MediaClass.CHANNEL
    assert listing.children[0].media_class == MediaClass.CHANNEL

    with patch.object(music_assistant_client.music, "search") as mock_search:
        mock_search.return_value = MagicMock(
            artists=[], albums=[], tracks=[], playlists=[], podcasts=[],
            audiobooks=[], radio=[],
        )
        await async_search_media(
            music_assistant_client,
            SearchMediaQuery(
                search_query="HR-Info", media_filter_classes={MediaClass.CHANNEL}
            ),
        )
    assert mock_search.call_args.kwargs["media_types"] == ["radio"]


def _item(name: str, media_type: str) -> MagicMock:
    item = MagicMock()
    item.name = name
    item.uri = f"library://{media_type}/{name}"
    item.available = True
    item.artists = []
    item.media_type = MagicMock(value=media_type)
    return item


async def test_exact_title_match_ranks_first(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """core#179557: the station named exactly comes before a track that contains it."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    results = MagicMock(
        artists=[],
        albums=[],
        tracks=[_item("HR-Info Remix", "track"), _item("hr-info", "track")],
        playlists=[],
        podcasts=[],
        audiobooks=[],
        radio=[_item("HR-Info", "radio")],
    )
    with patch.object(music_assistant_client.music, "search", return_value=results):
        search = await async_search_media(
            music_assistant_client, SearchMediaQuery(search_query="HR-Info")
        )
    titles = [item.title for item in search.result]
    assert titles == ["hr-info", "HR-Info", "HR-Info Remix"]
    assert search.result[1].media_class == MediaClass.CHANNEL


async def test_get_providers_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """feature-requests#4621: the configured providers are readable as an action."""
    music_assistant_client.providers = [
        ProviderInstance(
            type=ProviderType.MUSIC,
            domain="spotify",
            name="Spotify",
            instance_id="spotify--1",
            supported_features=set(),
            available=True,
            is_streaming_provider=True,
        ),
        ProviderInstance(
            type=ProviderType.PLAYER,
            domain="sonos",
            name="Sonos",
            instance_id="sonos--1",
            supported_features=set(),
            available=False,
        ),
    ]
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PROVIDERS,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response == {
        "providers": [
            {
                "instance_id": "spotify--1",
                "domain": "spotify",
                "name": "Spotify",
                "type": "music",
                "available": True,
                "is_streaming_provider": True,
            },
            {
                "instance_id": "sonos--1",
                "domain": "sonos",
                "name": "Sonos",
                "type": "player",
                "available": False,
                "is_streaming_provider": None,
            },
        ]
    }


async def test_sync_library_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """feature-requests#1718: a library sync can be started from an automation."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.start_sync = AsyncMock()
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SYNC_LIBRARY,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_MEDIA_TYPES: ["podcast"],
            ATTR_PROVIDERS: ["podcastfeed--1"],
        },
        blocking=True,
    )
    music_assistant_client.music.start_sync.assert_awaited_once_with(
        media_types=["podcast"], providers=["podcastfeed--1"]
    )

    await hass.services.async_call(
        DOMAIN, SERVICE_SYNC_LIBRARY, {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
    )
    assert music_assistant_client.music.start_sync.call_args.kwargs == {
        "media_types": None,
        "providers": None,
    }


async def test_search_with_provider_filter(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """feature-requests#2757: search can be restricted to providers."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.send_command = AsyncMock(return_value={})
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SEARCH,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_SEARCH_NAME: "Queen",
            ATTR_PROVIDERS: ["spotify", "library"],
        },
        blocking=True,
        return_response=True,
    )
    call = music_assistant_client.send_command.call_args
    assert call.args == ("music/search",)
    assert call.kwargs["providers"] == ["spotify", "library"]
    assert call.kwargs["search_query"] == "Queen"
    assert response["tracks"] == []


async def test_player_id_change_keeps_device_and_entities(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """core#181304: a player that returns under a new id keeps its entities."""
    players = create_players_from_fixture()
    original = next(player for player in players if player.player_id == PLAYER_ID)
    original.device_info.identifiers = {IdentifierType.MAC_ADDRESS: "AA:BB:CC:DD:EE:01"}
    with patch("tests.common.create_players_from_fixture", return_value=players):
        entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    old_entry = entity_registry.async_get(ENTITY_ID)
    assert old_entry is not None and old_entry.unique_id == PLAYER_ID
    old_device_id = old_entry.device_id
    old_button = entity_registry.async_get("button.test_player_1_favorite_current_song")
    assert old_button is not None

    renamed = deepcopy(original)
    renamed.player_id = "apaabbccddee01"
    del music_assistant_client.players._players[PLAYER_ID]
    music_assistant_client.players._players[renamed.player_id] = renamed
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, renamed.player_id
    )

    new_entry = entity_registry.async_get(ENTITY_ID)
    assert new_entry is not None
    assert new_entry.unique_id == renamed.player_id
    assert new_entry.device_id == old_device_id
    assert (
        entity_registry.async_get("button.test_player_1_favorite_current_song").unique_id
        == f"{renamed.player_id}_favorite_now_playing"
    )
    device = device_registry.async_get(old_device_id)
    assert device is not None
    assert (DOMAIN, renamed.player_id) in device.identifiers
    assert (DOMAIN, PLAYER_ID) not in device.identifiers
    assert renamed.player_id in entry.runtime_data.discovered_players
    assert PLAYER_ID not in entry.runtime_data.discovered_players
    assert hass.states.get(ENTITY_ID) is not None
    assert len(hass.states.async_entity_ids(MEDIA_PLAYER_DOMAIN)) == 3


async def test_player_id_change_is_ignored_while_old_player_exists(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Two live players sharing a MAC (a protocol wrapper) are not merged."""
    players = create_players_from_fixture()
    original = next(player for player in players if player.player_id == PLAYER_ID)
    original.device_info.identifiers = {IdentifierType.MAC_ADDRESS: "AA:BB:CC:DD:EE:01"}
    with patch("tests.common.create_players_from_fixture", return_value=players):
        entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    twin = deepcopy(original)
    twin.player_id = "twin"
    music_assistant_client.players._players["twin"] = twin
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, "twin"
    )
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, PLAYER_ID), entry.entry_id
    )
    assert device is not None
    assert PLAYER_ID in entry.runtime_data.discovered_players


@pytest.mark.parametrize("mac", [None, ""])
async def test_player_without_mac_is_never_migrated(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    mac: str | None,
) -> None:
    """Migration needs a MAC address; players without one are added as usual."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    player = deepcopy(music_assistant_client.players.get(PLAYER_ID))
    player.player_id = "fresh"
    if mac is not None:
        player.device_info.identifiers = {IdentifierType.MAC_ADDRESS: mac}
    music_assistant_client.players._players["fresh"] = player
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, "fresh"
    )
    assert {"fresh", PLAYER_ID} <= entry.runtime_data.discovered_players
