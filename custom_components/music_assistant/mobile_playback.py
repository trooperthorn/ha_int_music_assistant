"""Home Assistant actions for the branch-only local browser player."""

import base64
import binascii

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from music_assistant_client import MusicAssistantClient
import voluptuous as vol

from .const import DOMAIN
from .helpers import get_music_assistant_client

SERVICE_MOBILE_PLAY = "mobile_play"
SERVICE_MOBILE_CONTROL = "mobile_control"


def _verified_client_id(call: ServiceCall) -> str:
    """Bind a request to the browser identity encoded in its pairing token."""
    token: str = call.data["pairing_token"]
    if not token.upper().startswith("SP:0"):
        raise ServiceValidationError("Invalid local player pairing token")
    body = token[4:].upper().replace("9", "2")
    try:
        payload = base64.b32decode(body + "=" * (-len(body) % 8))
    except (ValueError, binascii.Error) as err:
        raise ServiceValidationError("Invalid local player pairing token") from err
    if len(payload) != 64:
        raise ServiceValidationError("Invalid local player pairing token")
    client_id = base64.urlsafe_b64encode(payload[:32]).rstrip(b"=").decode()
    if call.data["client_id"] != client_id:
        raise ServiceValidationError("Local player identity does not match its token")
    return client_id


async def _pair_local_player(call: ServiceCall) -> tuple[MusicAssistantClient, str]:
    """Pair the connected Sendspin web player using the existing MA client."""
    client_id = _verified_client_id(call)
    mass = get_music_assistant_client(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    await mass.send_command(
        "sendspin/pair_web_player", pairing_token=call.data["pairing_token"]
    )
    return mass, client_id


async def handle_mobile_play(call: ServiceCall) -> None:
    """Play a Music Assistant library URI in this browser's Sendspin player."""
    mass, client_id = await _pair_local_player(call)
    await mass.player_queues.play_media(client_id, media=[call.data["media_id"]])


async def handle_mobile_control(call: ServiceCall) -> None:
    """Control only the browser player proven by its pairing token."""
    mass, client_id = await _pair_local_player(call)
    commands = {
        "play": mass.player_queues.play,
        "pause": mass.player_queues.pause,
        "next": mass.player_queues.next,
        "previous": mass.player_queues.previous,
        "stop": mass.player_queues.stop,
    }
    await commands[call.data["command"]](client_id)


@callback
def register_mobile_actions(hass: HomeAssistant) -> None:
    """Register local playback actions independently of remote player entities."""
    identity = {
        vol.Required(ATTR_CONFIG_ENTRY_ID): str,
        vol.Required("client_id"): str,
        vol.Required("pairing_token"): str,
    }
    hass.services.async_register(
        DOMAIN,
        SERVICE_MOBILE_PLAY,
        handle_mobile_play,
        schema=vol.Schema({**identity, vol.Required("media_id"): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MOBILE_CONTROL,
        handle_mobile_control,
        schema=vol.Schema(
            {**identity, vol.Required("command"): vol.In(("play", "pause", "next", "previous", "stop"))}
        ),
    )

