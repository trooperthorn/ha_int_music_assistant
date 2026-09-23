"""Register the branch-only Music Assistant panel in Home Assistant."""

import asyncio
from contextlib import suppress
import json
from pathlib import Path

from aiohttp import ClientError, ClientWebSocketResponse, WSMsgType, web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_VERIFY_SSL, DOMAIN

PANEL_PATH = "music-assistant-mobile"
PANEL_MODULE_URL = "/api/music_assistant_mobile/panel.js"
BUBBLE_MODULE_URL = "/api/music_assistant_mobile/bubble.js"
_STATIC_REGISTERED = f"{DOMAIN}_mobile_static_registered"
_PROXY_REGISTERED = f"{DOMAIN}_mobile_proxy_registered"


class LocalSendspinProxyView(HomeAssistantView):
    """Forward an authenticated HA browser player to the MA Sendspin endpoint."""

    url = "/api/music_assistant_mobile/sendspin/{entry_id}"
    name = "api:music_assistant_mobile:sendspin"

    async def get(self, request: web.Request, entry_id: str) -> web.WebSocketResponse:
        """Authenticate the HA request, then bridge Sendspin frames bidirectionally."""
        hass: HomeAssistant = request.app[KEY_HASS]
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise web.HTTPNotFound()
        token = entry.data.get(CONF_TOKEN)
        if not token:
            raise web.HTTPServiceUnavailable(reason="Music Assistant token unavailable")

        browser_ws = web.WebSocketResponse(heartbeat=25, max_msg_size=0)
        await browser_ws.prepare(request)
        try:
            async with asyncio.timeout(10):
                hello = await browser_ws.receive()
            if hello.type is not WSMsgType.TEXT:
                await browser_ws.close(code=4001, message=b"Client identity required")
                return browser_ws
            payload = json.loads(hello.data)
            if not isinstance(payload, dict):
                await browser_ws.close(code=4001, message=b"Invalid client identity")
                return browser_ws
            client_id = payload.get("client_id")
            if (
                payload.get("type") != "auth"
                or not isinstance(client_id, str)
                or len(client_id) != 43
            ):
                await browser_ws.close(code=4001, message=b"Invalid client identity")
                return browser_ws

            base_url = entry.data[CONF_URL].rstrip("/")
            upstream_url = base_url.replace("https://", "wss://", 1).replace(
                "http://", "ws://", 1
            ) + "/sendspin"
            session = async_get_clientsession(
                hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            )
            async with session.ws_connect(
                upstream_url, heartbeat=25, max_msg_size=0
            ) as upstream_ws:
                await upstream_ws.send_json(
                    {"type": "auth", "token": token, "client_id": client_id}
                )
                async with asyncio.timeout(10):
                    reply = await upstream_ws.receive()
                reply_data = json.loads(reply.data) if reply.type is WSMsgType.TEXT else {}
                if not isinstance(reply_data, dict) or reply_data.get("type") != "auth_ok":
                    await browser_ws.close(code=4001, message=b"Music Assistant authentication failed")
                    return browser_ws
                await browser_ws.send_str('{"type":"auth_ok"}')
                tasks = {
                    asyncio.create_task(self._forward(browser_ws, upstream_ws)),
                    asyncio.create_task(self._forward(upstream_ws, browser_ws)),
                }
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (TimeoutError, ValueError, ClientError, web.HTTPException):
            with suppress(ConnectionError):
                await browser_ws.close(code=1011, message=b"Local player connection failed")
        finally:
            if not browser_ws.closed:
                await browser_ws.close()
        return browser_ws

    @staticmethod
    async def _forward(
        source: web.WebSocketResponse | ClientWebSocketResponse,
        destination: web.WebSocketResponse | ClientWebSocketResponse,
    ) -> None:
        """Preserve binary audio and text control frames without translating them."""
        async for message in source:
            if message.type is WSMsgType.BINARY:
                await destination.send_bytes(message.data)
            elif message.type is WSMsgType.TEXT:
                await destination.send_str(message.data)
            else:
                break


async def async_setup_mobile_panel(hass: HomeAssistant) -> None:
    """Serve the bundled Lit page and add it to Home Assistant's sidebar."""
    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_MODULE_URL,
                    str(Path(__file__).parent / "mobile" / "panel.js"),
                    False,
                ),
                StaticPathConfig(
                    BUBBLE_MODULE_URL,
                    str(Path(__file__).parent / "mobile" / "bubble.js"),
                    False,
                ),
            ]
        )
        hass.data[_STATIC_REGISTERED] = True

    frontend.add_extra_js_url(hass, BUBBLE_MODULE_URL)
    if not hass.data.get(_PROXY_REGISTERED):
        hass.http.register_view(LocalSendspinProxyView())
        hass.data[_PROXY_REGISTERED] = True

    if frontend.async_panel_exists(hass, PANEL_PATH):
        return

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="ma-mobile-panel",
        sidebar_title="Music",
        sidebar_icon="mdi:music-note",
        module_url=PANEL_MODULE_URL,
        embed_iframe=False,
        handle_safe_area=False,
    )

