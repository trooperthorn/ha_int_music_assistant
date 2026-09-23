"""Verify local browser playback cannot target another Sendspin identity."""

import base64
from unittest.mock import AsyncMock

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.music_assistant.const import DOMAIN
from custom_components.music_assistant.mobile_playback import SERVICE_MOBILE_PLAY

from .common import setup_integration_from_fixtures


async def test_mobile_play_pairs_and_targets_its_own_browser(
    hass: HomeAssistant, music_assistant_client: AsyncMock
) -> None:
    """A valid browser token pairs and queues an item on that same identity."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    key = bytes(range(32))
    token = "SP:0" + base64.b32encode(key + bytes(range(32, 64))).decode().rstrip("=").replace("2", "9")
    client_id = base64.urlsafe_b64encode(key).decode().rstrip("=")
    music_assistant_client.player_queues.play_media = AsyncMock()

    await hass.services.async_call(
        DOMAIN, SERVICE_MOBILE_PLAY,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, "client_id": client_id, "pairing_token": token, "media_id": "library://track/42"},
        blocking=True,
    )
    music_assistant_client.send_command.assert_awaited_with(
        "sendspin/pair_web_player", pairing_token=token
    )
    music_assistant_client.player_queues.play_media.assert_awaited_once_with(
        client_id, media=["library://track/42"]
    )


async def test_mobile_play_rejects_other_browser_identity(
    hass: HomeAssistant, music_assistant_client: AsyncMock
) -> None:
    """The API cannot direct a pairing token at an unrelated player ID."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    token = "SP:0" + base64.b32encode(bytes(range(64))).decode().rstrip("=").replace("2", "9")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_MOBILE_PLAY,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, "client_id": "wrong", "pairing_token": token, "media_id": "library://track/42"},
            blocking=True,
        )
    music_assistant_client.send_command.assert_not_awaited()

