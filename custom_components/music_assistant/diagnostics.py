"""Diagnostics support for Music Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from . import MusicAssistantConfigEntry

TO_REDACT = {
    CONF_TOKEN,
    CONF_URL,
    "base_url",
    "server_id",
    "ip_address",
    "identifiers",
    "manufacturer_id",
}
QUEUE_TO_REDACT = {"items", "name", "uri", "title", "media_item", "image"}


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
        "server_info": async_redact_data(server_info, TO_REDACT)
        if server_info is not None
        else None,
        "discovered_players": sorted(entry.runtime_data.discovered_players),
        "players": async_redact_data(players, TO_REDACT),
        "queues": async_redact_data(queues, QUEUE_TO_REDACT),
        "providers": providers,
    }
