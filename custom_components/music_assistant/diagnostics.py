"""Diagnostics support for Music Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from . import MusicAssistantConfigEntry

TO_REDACT = {CONF_TOKEN, "ip_address", "identifiers", "manufacturer_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MusicAssistantConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    mass = entry.runtime_data.mass
    server_info = mass.server_info.to_dict() if mass.server_info else None
    players = [player.to_dict() for player in mass.players]
    queues = [
        {
            "queue_id": queue.queue_id,
            "display_name": queue.display_name,
            "active": queue.active,
            "state": queue.state.value,
            "items": queue.items,
            "current_index": queue.current_index,
            "shuffle_enabled": queue.shuffle_enabled,
            "repeat_mode": queue.repeat_mode.value,
        }
        for queue in mass.player_queues
    ]
    providers = [
        {
            "instance_id": provider.instance_id,
            "domain": provider.domain,
            "name": provider.name,
            "type": provider.type.value,
            "available": provider.available,
        }
        for provider in mass.providers
    ]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "connected": bool(mass.connection.connected),
        "server_info": server_info,
        "discovered_players": sorted(entry.runtime_data.discovered_players),
        "players": async_redact_data(players, TO_REDACT),
        "queues": queues,
        "providers": providers,
    }
