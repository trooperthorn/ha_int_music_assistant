"""Music Assistant (music-assistant.io) integration."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from music_assistant_client import MusicAssistantClient
from music_assistant_client.exceptions import (
    CannotConnect,
    InvalidServerVersion,
    MusicAssistantClientException,
)
from music_assistant_models.config_entries import PlayerConfig
from music_assistant_models.enums import EventType, IdentifierType
from music_assistant_models.errors import (
    ActionUnavailable,
    AuthenticationFailed,
    AuthenticationRequired,
    InvalidToken,
    MusicAssistantError,
)
from music_assistant_models.player import Player

from .const import ATTR_CONF_EXPOSE_PLAYER_TO_HA, DEFAULT_VERIFY_SSL, DOMAIN, LOGGER
from .intent import async_setup_intents
from .services import register_actions

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType
    from music_assistant_models.event import MassEvent

PLATFORMS = [
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
]

CONNECT_TIMEOUT = 10
LISTEN_READY_TIMEOUT = 30

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MusicAssistantConfigEntry = ConfigEntry[MusicAssistantEntryData]
type PlayerAddCallback = Callable[[str], None]


@dataclass
class MusicAssistantEntryData:
    """Hold Mass data for the config entry."""

    mass: MusicAssistantClient
    listen_task: asyncio.Task[None]
    discovered_players: set[str] = field(default_factory=set)
    platform_handlers: dict[Platform, PlayerAddCallback] = field(default_factory=dict)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Music Assistant component."""
    hass.data.setdefault(DOMAIN, set())
    register_actions(hass)
    async_setup_intents(hass)

    return True


def _lost_connections(hass: HomeAssistant) -> set[str]:
    """Return the entry ids whose server connection is logged as lost."""
    lost: set[str] = hass.data.setdefault(DOMAIN, set())
    return lost


def _log_connection_lost(hass: HomeAssistant, entry: ConfigEntry, reason: str) -> None:
    """Log the loss of the server connection once until it is restored."""
    lost = _lost_connections(hass)
    if entry.entry_id in lost:
        return
    lost.add(entry.entry_id)
    LOGGER.info(
        "Connection to Music Assistant server %s lost: %s",
        entry.data[CONF_URL],
        reason,
    )


def _log_connection_restored(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Log the return of the server connection if its loss was logged."""
    lost = _lost_connections(hass)
    if entry.entry_id not in lost:
        return
    lost.discard(entry.entry_id)
    LOGGER.info(
        "Connection to Music Assistant server %s restored", entry.data[CONF_URL]
    )


def _describe(err: BaseException) -> str:
    """Return a non-empty description of an exception."""
    return str(err) or err.__class__.__name__


async def async_setup_entry(
    hass: HomeAssistant, entry: MusicAssistantConfigEntry
) -> bool:
    """Set up Music Assistant from a config entry."""
    verify_ssl: bool = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    http_session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    mass_url = entry.data[CONF_URL]
    token = entry.data.get(CONF_TOKEN)
    mass = MusicAssistantClient(mass_url, http_session, token=token)

    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await mass.connect()
    except (TimeoutError, CannotConnect) as err:
        _log_connection_lost(hass, entry, _describe(err))
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"url": mass_url, "error": _describe(err)},
        ) from err
    except InvalidServerVersion as err:
        async_create_issue(
            hass,
            DOMAIN,
            "invalid_server_version",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key="invalid_server_version",
        )
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="invalid_server_version",
            translation_placeholders={"error": _describe(err)},
        ) from err
    except (AuthenticationRequired, AuthenticationFailed, InvalidToken) as err:
        assert mass.server_info is not None
        if mass.server_info.homeassistant_addon:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="addon_discovery_pending",
            ) from err
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"url": mass_url, "error": _describe(err)},
        ) from err
    except MusicAssistantClientException as err:
        _log_connection_lost(hass, entry, _describe(err))
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"url": mass_url, "error": _describe(err)},
        ) from err
    except MusicAssistantError as err:
        LOGGER.exception("Failed to connect to music assistant server", exc_info=err)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="unknown_error",
            translation_placeholders={"url": mass_url, "error": _describe(err)},
        ) from err

    async_delete_issue(hass, DOMAIN, "invalid_server_version")

    async def on_hass_stop(event: Event) -> None:
        """Handle incoming stop event from Home Assistant."""
        await mass.disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )

    init_ready = asyncio.Event()
    listen_task = asyncio.create_task(_client_listen(hass, entry, mass, init_ready))

    try:
        async with asyncio.timeout(LISTEN_READY_TIMEOUT):
            await init_ready.wait()
    except TimeoutError as err:
        listen_task.cancel()
        await mass.disconnect()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="listen_not_ready",
            translation_placeholders={"url": mass_url},
        ) from err

    if listen_task.done() and (listen_error := listen_task.exception()) is not None:
        await mass.disconnect()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={
                "url": mass_url,
                "error": _describe(listen_error),
            },
        ) from listen_error

    entry.runtime_data = MusicAssistantEntryData(mass, listen_task)
    _log_connection_restored(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def add_player(player: Player) -> None:
        """Handle adding Player from MA as HA device + entities."""
        _migrate_player_identity(hass, entry, player)
        entry.runtime_data.discovered_players.add(player.player_id)
        for callback in entry.runtime_data.platform_handlers.values():
            callback(player.player_id)

    def remove_player(player_id: str) -> None:
        """Handle removing Player from MA as HA device + entities."""
        entry.runtime_data.discovered_players.discard(player_id)
        dev_reg = dr.async_get(hass)
        if hass_device := dev_reg.async_get_device_by_identifier(
            (DOMAIN, player_id), entry.entry_id
        ):
            dev_reg.async_remove_device(hass_device.id)

    def handle_player_added(event: MassEvent) -> None:
        """Handle Mass Player Added event."""
        if TYPE_CHECKING:
            assert event.object_id is not None
        if event.object_id in entry.runtime_data.discovered_players:
            return
        player = mass.players.get(event.object_id)
        if player is None or not player.expose_to_ha:
            return
        add_player(player)

    entry.async_on_unload(mass.subscribe(handle_player_added, EventType.PLAYER_ADDED))

    for player in mass.players:
        if not player.expose_to_ha:
            continue
        add_player(player)

    def handle_player_removed(event: MassEvent) -> None:
        """Handle Mass Player Removed event."""
        if event.object_id is None:
            return
        remove_player(event.object_id)

    entry.async_on_unload(
        mass.subscribe(handle_player_removed, EventType.PLAYER_REMOVED)
    )

    def handle_player_config_updated(event: MassEvent) -> None:
        """Handle the expose_to_ha toggle in a Player Config Updated event."""
        if event.object_id is None or not event.data:
            return
        player_id = event.object_id
        player_config = PlayerConfig.from_dict(event.data)
        expose_to_ha = player_config.get_value(ATTR_CONF_EXPOSE_PLAYER_TO_HA, True)
        if not expose_to_ha and player_id in entry.runtime_data.discovered_players:
            remove_player(player_id)
        elif expose_to_ha and player_id not in entry.runtime_data.discovered_players:
            if not (player := mass.players.get(player_id)):
                return
            add_player(player)

    entry.async_on_unload(
        mass.subscribe(handle_player_config_updated, EventType.PLAYER_CONFIG_UPDATED)
    )

    all_player_configs = await mass.config.get_player_configs()
    player_ids = {player.player_id for player in all_player_configs}
    dev_reg = dr.async_get(hass)
    dev_entries = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    for device in dev_entries:
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN and identifier[1] not in player_ids:
                dev_reg.async_remove_device(device.id)

    return True


def _migrate_player_identity(
    hass: HomeAssistant, entry: ConfigEntry, player: Player
) -> None:
    """Carry a device and its entities over to a player id that changed.

    The server derives some player ids from what the device advertises, and
    a device that speaks several protocols (WiiM over AirPlay and its own
    protocol) can come back under a different id after an update. The MAC
    address is stable, so a device in this entry that carries the same MAC
    under another id is renamed to the new id, along with the unique ids of
    its entities.
    """
    mac = player.device_info.identifiers.get(IdentifierType.MAC_ADDRESS)
    if not mac:
        return
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device_by_connection(
        (dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac)), entry.entry_id
    )
    if device is None:
        return
    old_id = next(
        (
            identifier[1]
            for identifier in device.identifiers
            if identifier[0] == DOMAIN and identifier[1] != player.player_id
        ),
        None,
    )
    if old_id is None or (DOMAIN, player.player_id) in device.identifiers:
        return
    if mass_has_player(entry, old_id):
        return
    LOGGER.info(
        "Player %s changed its id from %s to %s; keeping its device and entities",
        player.name,
        old_id,
        player.player_id,
    )
    dev_reg.async_update_device(
        device.id, new_identifiers={(DOMAIN, player.player_id)}
    )
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_device(ent_reg, device.id, True):
        if entity.platform != DOMAIN:
            continue
        if entity.unique_id == old_id:
            new_unique_id = player.player_id
        elif entity.unique_id.startswith(f"{old_id}_"):
            new_unique_id = f"{player.player_id}{entity.unique_id[len(old_id):]}"
        else:
            continue
        ent_reg.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)
    entry.runtime_data.discovered_players.discard(old_id)


def mass_has_player(entry: ConfigEntry, player_id: str) -> bool:
    """Return whether the server still knows a player by this id."""
    runtime: MusicAssistantEntryData = entry.runtime_data
    return runtime.mass.players.get(player_id) is not None


async def _client_listen(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mass: MusicAssistantClient,
    init_ready: asyncio.Event,
) -> None:
    """Listen with the client."""
    reason = "connection closed"
    try:
        await mass.start_listening(init_ready)
    except MusicAssistantError as err:
        if entry.state is not ConfigEntryState.LOADED:
            raise
        reason = _describe(err)
    except Exception as err:
        if entry.state is not ConfigEntryState.LOADED:
            raise
        LOGGER.exception("Unexpected exception: %s", err)
        reason = _describe(err)

    if not hass.is_stopping:
        _log_connection_lost(hass, entry, reason)
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))


async def async_unload_entry(
    hass: HomeAssistant, entry: MusicAssistantConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        mass_entry_data = entry.runtime_data
        mass_entry_data.listen_task.cancel()
        await mass_entry_data.mass.disconnect()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the connection bookkeeping of a removed entry."""
    _lost_connections(hass).discard(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: MusicAssistantConfigEntry,
    device_entry: dr.AnyDeviceEntry,
) -> bool:
    """Remove a config entry from a device."""
    player_id = next(
        (
            identifier[1]
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        ),
        None,
    )
    if player_id is None:
        return False
    if config_entry.state is not ConfigEntryState.LOADED:
        return False
    mass = config_entry.runtime_data.mass
    if mass.players.get(player_id) is None:
        return True
    try:
        await mass.config.remove_player_config(player_id)
    except ActionUnavailable:
        return False
    else:
        return True
