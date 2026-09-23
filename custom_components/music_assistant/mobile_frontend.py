"""Register the branch-only Music Assistant panel in Home Assistant."""

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_PATH = "music-assistant-mobile"
PANEL_MODULE_URL = "/api/music_assistant_mobile/panel.js"
BUBBLE_MODULE_URL = "/api/music_assistant_mobile/bubble.js"
_STATIC_REGISTERED = f"{DOMAIN}_mobile_static_registered"


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

