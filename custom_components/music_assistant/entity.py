"""Base entity model."""

from typing import TYPE_CHECKING, override

from homeassistant.const import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from music_assistant_models.enums import EventType, IdentifierType
from music_assistant_models.event import MassEvent
from music_assistant_models.player import Player, PlayerOption

from .const import DOMAIN

if TYPE_CHECKING:
    from music_assistant_client import MusicAssistantClient


def player_configuration_url(mass: MusicAssistantClient, player_id: str) -> str:
    """Return the browser URL of the player's settings page.

    The integration may talk to the server over an internal-only address (the
    Home Assistant app exposes a second webserver for it), so the address a
    browser can reach is taken from the server info when the server reports one.
    """
    base = mass.server_url
    if (info := mass.server_info) is not None:
        base = info.external_url or info.base_url or base
    return f"{base.rstrip('/')}/#/settings/editplayer/{player_id}"


def player_device_info(mass: MusicAssistantClient, player: Player) -> DeviceInfo:
    """Build the Home Assistant device record for a Music Assistant player."""
    provider = mass.get_provider(player.provider, return_unavailable=True)
    provider_name = provider.name if provider is not None else player.provider
    info = player.device_info
    device_info = DeviceInfo(
        identifiers={(DOMAIN, player.player_id)},
        manufacturer=info.manufacturer or provider_name,
        model=info.model or player.name,
        name=player.name,
        configuration_url=player_configuration_url(mass, player.player_id),
    )
    if info.model_id:
        device_info["model_id"] = info.model_id
    if info.software_version:
        device_info["sw_version"] = info.software_version
    if mac := info.identifiers.get(IdentifierType.MAC_ADDRESS):
        device_info["connections"] = {(dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))}
    if serial := info.identifiers.get(IdentifierType.SERIAL_NUMBER):
        device_info["serial_number"] = serial
    return device_info


class MusicAssistantEntity(Entity):
    """Base Entity from Music Assistant Player."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, mass: MusicAssistantClient, player_id: str) -> None:
        """Initialize MediaPlayer entity."""
        self.mass = mass
        self.player_id = player_id
        self._attr_device_info = player_device_info(mass, self.player)

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await self.async_on_update()
        self.async_on_remove(
            self.mass.subscribe(
                self.__on_mass_update, EventType.PLAYER_UPDATED, self.player_id
            )
        )
        self.async_on_remove(
            self.mass.subscribe(
                self.__on_mass_update,
                EventType.QUEUE_UPDATED,
            )
        )

    @property
    def player(self) -> Player:
        """Return the Mass Player attached to this HA entity."""
        return self.mass.players[self.player_id]

    @property
    @override
    def unique_id(self) -> str | None:
        """Return unique id for entity."""
        _base = self.player_id
        if hasattr(self, "entity_description"):
            return f"{_base}_{self.entity_description.key}"
        return _base

    @property
    @override
    def available(self) -> bool:
        """Return availability of entity."""
        player = self.mass.players.get(self.player_id)
        return (
            player is not None
            and player.available
            and bool(self.mass.connection.connected)
        )

    async def __on_mass_update(self, event: MassEvent) -> None:
        """Call when we receive an event from MusicAssistant."""
        player = self.mass.players.get(self.player_id)
        if player is None:
            return
        if event.event == EventType.QUEUE_UPDATED and event.object_id not in (
            player.active_source,
            player.active_group,
            player.player_id,
        ):
            return
        await self.async_on_update()
        self.async_write_ha_state()

    async def async_on_update(self) -> None:
        """Handle player updates."""


class MusicAssistantPlayerOptionEntity(MusicAssistantEntity):
    """Base entity for Music Assistant Player Options."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, mass: MusicAssistantClient, player_id: str, player_option: PlayerOption
    ) -> None:
        """Initialize MusicAssistantPlayerOptionEntity."""
        super().__init__(mass, player_id)

        self.mass_option_key = player_option.key
        self.mass_type = player_option.type

        self.on_player_option_update(player_option)

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()

        self.async_on_remove(
            self.mass.subscribe(
                self.__on_mass_player_options_update,
                EventType.PLAYER_OPTIONS_UPDATED,
                self.player_id,
            )
        )

    def __on_mass_player_options_update(self, event: MassEvent) -> None:
        """Call when we receive an event from MusicAssistant."""
        for option in self.player.options:
            if option.key == self.mass_option_key:
                self.on_player_option_update(option)
                self.async_write_ha_state()
                break

    def on_player_option_update(self, player_option: PlayerOption) -> None:
        """Callback for player option updates."""
