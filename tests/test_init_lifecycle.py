"""Setup, listen-task, and player lifecycle paths of the integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN, CONF_URL, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from music_assistant_client.exceptions import (
    InvalidServerVersion,
    MusicAssistantClientException,
)
from music_assistant_models.enums import EventType
from music_assistant_models.errors import MusicAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.music_assistant import async_remove_config_entry_device
from custom_components.music_assistant.const import DOMAIN

from .common import setup_integration_from_fixtures, trigger_subscription_callback

PLAYER_ID = "00:00:00:00:00:01"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Music Assistant",
        data={CONF_URL: "http://localhost:8095", CONF_TOKEN: "token"},
        unique_id="1234",
    )


async def test_invalid_server_version_creates_repair(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An unsupported server raises a repair issue and retries."""
    entry = _entry()
    entry.add_to_hass(hass)
    music_assistant_client.connect.side_effect = InvalidServerVersion("old")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert issue_registry.async_get_issue(DOMAIN, "invalid_server_version")

    music_assistant_client.connect.side_effect = None
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, "invalid_server_version") is None


@pytest.mark.parametrize(
    "exception",
    [MusicAssistantClientException("client"), MusicAssistantError("server")],
)
async def test_other_connect_errors_retry(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    exception: Exception,
) -> None:
    """Client and server errors during connect lead to a retry."""
    entry = _entry()
    entry.add_to_hass(hass)
    music_assistant_client.connect.side_effect = exception
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_listen_never_ready_retries(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A listener that never signals readiness is cancelled and setup retried."""
    entry = _entry()
    entry.add_to_hass(hass)

    async def never_ready(init_ready: asyncio.Event) -> None:
        await asyncio.Event().wait()

    music_assistant_client.start_listening = AsyncMock(side_effect=never_ready)
    with pytest_timeout_patch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    music_assistant_client.disconnect.assert_awaited()


class pytest_timeout_patch:
    """Shrink the listen-ready timeout for the duration of a test."""

    def __enter__(self) -> None:
        from custom_components import music_assistant as component

        self._old = component.LISTEN_READY_TIMEOUT
        component.LISTEN_READY_TIMEOUT = 0

    def __exit__(self, *exc: object) -> None:
        from custom_components import music_assistant as component

        component.LISTEN_READY_TIMEOUT = self._old


async def test_listen_fails_before_ready_retries(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A listener that dies before the entry is loaded fails setup with a retry."""
    entry = _entry()
    entry.add_to_hass(hass)

    async def fail_fast(init_ready: asyncio.Event) -> None:
        init_ready.set()
        raise MusicAssistantError("gone")

    music_assistant_client.start_listening = AsyncMock(side_effect=fail_fast)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    "exception", [MusicAssistantError("dropped"), RuntimeError("unexpected")]
)
async def test_listen_drop_after_load_reloads(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    exception: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A listener that dies after load logs the loss once and reloads the entry."""
    release = asyncio.Event()

    async def listen(init_ready: asyncio.Event) -> None:
        init_ready.set()
        await release.wait()
        raise exception

    music_assistant_client.start_listening = AsyncMock(side_effect=listen)
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    assert entry.state is ConfigEntryState.LOADED

    reload_calls: list[str] = []
    original_reload = hass.config_entries.async_reload

    async def fake_reload(entry_id: str) -> bool:
        reload_calls.append(entry_id)
        release.clear()
        return await original_reload(entry_id)

    hass.config_entries.async_reload = fake_reload  # type: ignore[method-assign]
    release.set()
    await hass.async_block_till_done()
    assert reload_calls == [entry.entry_id]
    assert "lost" in caplog.text
    assert caplog.text.count("Connection to Music Assistant server") == 2


async def test_hass_stop_disconnects(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Home Assistant shutdown disconnects the client."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.disconnect.reset_mock()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    music_assistant_client.disconnect.assert_awaited()


async def test_player_added_and_removed_events(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """PLAYER_ADDED and PLAYER_REMOVED events add and remove devices."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    entity_id = "media_player.test_player_1"

    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_REMOVED, PLAYER_ID
    )
    assert PLAYER_ID not in entry.runtime_data.discovered_players
    assert hass.states.get(entity_id) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, PLAYER_ID), entry.entry_id
        )
        is None
    )

    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, PLAYER_ID
    )
    assert PLAYER_ID in entry.runtime_data.discovered_players
    assert hass.states.get(entity_id)

    # A second add for a known player and an add for an unknown id are ignored
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, PLAYER_ID
    )
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, "no-such-player"
    )
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_REMOVED, None
    )
    assert "no-such-player" not in entry.runtime_data.discovered_players


async def test_unexposed_player_is_skipped_on_add(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """A PLAYER_ADDED event for a player hidden from HA creates nothing."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_REMOVED, PLAYER_ID
    )
    music_assistant_client.players.get(PLAYER_ID).expose_to_ha = False
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_ADDED, PLAYER_ID
    )
    assert PLAYER_ID not in entry.runtime_data.discovered_players


async def test_remove_orphaned_device(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A device whose player the server no longer knows can always be removed."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, PLAYER_ID), entry.entry_id
    )
    assert device is not None
    del music_assistant_client.players._players[PLAYER_ID]
    assert await async_remove_config_entry_device(hass, entry, device) is True

    foreign = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("other", "x")}
    )
    assert await async_remove_config_entry_device(hass, entry, foreign) is False


async def test_entry_removal_forgets_connection_bookkeeping(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Removing the entry clears its connection-lost record."""
    entry = _entry()
    entry.add_to_hass(hass)
    music_assistant_client.connect.side_effect = MusicAssistantClientException("x")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id in hass.data[DOMAIN]
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]
