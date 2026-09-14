"""Test Music Assistant config entry diagnostics."""

from unittest.mock import MagicMock

from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from music_assistant_models.enums import ProviderType
from music_assistant_models.provider import ProviderInstance

from custom_components.music_assistant.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import setup_integration_from_fixtures


async def test_diagnostics_redacts_token_and_lists_players(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """The token is redacted; players, queues, and providers are listed."""
    music_assistant_client.providers = [
        ProviderInstance(
            type=ProviderType.PLAYER,
            domain="test",
            name="Test provider",
            instance_id="test--1",
            supported_features=set(),
            available=True,
        )
    ]
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_TOKEN: "secret"}
    )

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["entry"][CONF_TOKEN] == "**REDACTED**"
    assert result["entry"][CONF_URL] == config_entry.data[CONF_URL]
    assert result["connected"] is True
    assert result["server_info"]["server_id"] == "1234"
    assert sorted(result["discovered_players"]) == result["discovered_players"]
    assert len(result["players"]) == len(list(music_assistant_client.players))
    assert {queue["queue_id"] for queue in result["queues"]} == {
        queue.queue_id for queue in music_assistant_client.player_queues
    }
    assert result["providers"] == [
        {
            "instance_id": "test--1",
            "domain": "test",
            "name": "Test provider",
            "type": "player",
            "available": True,
        }
    ]
    for player in result["players"]:
        assert player["device_info"]["identifiers"] == "**REDACTED**"
