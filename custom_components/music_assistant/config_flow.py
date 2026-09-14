"""Config flow for MusicAssistant integration."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override
from urllib.parse import urlencode

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.config_entry_oauth2_flow import (
    _encode_jwt,
    async_get_redirect_uri,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from music_assistant_client import MusicAssistantClient
from music_assistant_client.auth_helpers import create_long_lived_token, get_server_info
from music_assistant_client.exceptions import (
    CannotConnect,
    InvalidServerVersion,
    MusicAssistantClientException,
)
from music_assistant_models.api import ServerInfoMessage
from music_assistant_models.errors import (
    AuthenticationFailed,
    AuthenticationRequired,
    InvalidToken,
)
import voluptuous as vol

from .const import (
    AUTH_SCHEMA_VERSION,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    HASSIO_DISCOVERY_SCHEMA_VERSION,
    LOGGER,
)

DEFAULT_TITLE = "Music Assistant"
DEFAULT_URL = "http://mass.local:8095"


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)
STEP_AUTH_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


def _parse_zeroconf_server_info(properties: dict[str, str]) -> ServerInfoMessage:
    """Parse zeroconf properties to ServerInfoMessage."""

    return ServerInfoMessage(
        server_id=properties["server_id"],
        server_version=properties["server_version"],
        schema_version=int(properties["schema_version"]),
        min_supported_schema_version=int(properties["min_supported_schema_version"]),
        base_url=properties["base_url"],
        homeassistant_addon=properties["homeassistant_addon"].lower() == "true",
        onboard_done=properties["onboard_done"].lower() == "true",
    )


async def _get_server_info(
    hass: HomeAssistant, url: str, verify_ssl: bool = True
) -> ServerInfoMessage:
    """Get MA server info for the given URL."""
    session = aiohttp_client.async_get_clientsession(hass, verify_ssl=verify_ssl)
    return await get_server_info(server_url=url, aiohttp_session=session)


async def _test_connection(
    hass: HomeAssistant, url: str, token: str, verify_ssl: bool = True
) -> None:
    """Test connection to MA server with given URL and token."""
    session = aiohttp_client.async_get_clientsession(hass, verify_ssl=verify_ssl)
    async with MusicAssistantClient(
        server_url=url,
        aiohttp_session=session,
        token=token,
    ) as client:
        # Just executing any command to test the connection.
        # If auth is required and the token is invalid, this will raise.
        await client.send_command("info")


class MusicAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MusicAssistant."""

    VERSION = 1

    def __init__(self) -> None:
        """Set up flow instance."""
        self.url: str | None = None
        self.token: str | None = None
        self.verify_ssl: bool = True
        self.server_info: ServerInfoMessage | None = None

    def _entry_data(self, token: str | None) -> dict[str, Any]:
        """Return the config entry data for the collected url, token and TLS choice."""
        data: dict[str, Any] = {CONF_URL: self.url, CONF_VERIFY_SSL: self.verify_ssl}
        if token:
            data[CONF_TOKEN] = token
        return data

    def _finish(self, token: str | None) -> ConfigFlowResult:
        """Create the entry, or update the entry being reauthenticated or reconfigured."""
        data = self._entry_data(token)
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=DEFAULT_TITLE, data=data)

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a manual configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.url = user_input[CONF_URL]
            self.verify_ssl = user_input[CONF_VERIFY_SSL]
            try:
                server_info = await _get_server_info(
                    self.hass, self.url, self.verify_ssl
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidServerVersion:
                errors["base"] = "invalid_server_version"
            except MusicAssistantClientException:
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self.server_info = server_info
                await self.async_set_unique_id(
                    server_info.server_id, raise_on_progress=False
                )
                self._abort_if_unique_id_configured(
                    updates={CONF_URL: self.url, CONF_VERIFY_SSL: self.verify_ssl}
                )

                if server_info.schema_version >= AUTH_SCHEMA_VERSION:
                    return await self.async_step_auth()

                return self._finish(None)

        suggested_values = user_input
        if suggested_values is None:
            suggested_values = {CONF_URL: DEFAULT_URL, CONF_VERIFY_SSL: True}

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, suggested_values
            ),
            errors=errors,
        )

    @override
    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle Home Assistant app discovery.

        This flow is triggered by the Music Assistant app.
        """
        # Build URL from app discovery info
        # The app exposes the API on port 8095, but also
        # hosts an internal-only webserver (default at port
        # 8094) for the HA integration to connect to.
        # The info where the internal API is exposed is
        # passed via discovery_info
        host = discovery_info.config["host"]
        port = discovery_info.config["port"]
        self.url = f"http://{host}:{port}"
        try:
            server_info = await _get_server_info(self.hass, self.url)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except InvalidServerVersion:
            return self.async_abort(reason="invalid_server_version")
        except MusicAssistantClientException:
            LOGGER.exception("Unexpected exception during HA app discovery")
            return self.async_abort(reason="unknown")

        # We trust the token from hassio discovery and validate it during setup
        self.token = discovery_info.config["auth_token"]

        self.server_info = server_info

        # Check if there's an existing entry
        if entry := await self.async_set_unique_id(server_info.server_id):
            updated = self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_URL: self.url, CONF_TOKEN: self.token}
            )
            if updated and entry.state in (
                ConfigEntryState.LOADED,
                ConfigEntryState.SETUP_ERROR,
                ConfigEntryState.SETUP_RETRY,
                ConfigEntryState.SETUP_IN_PROGRESS,
            ):
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

            # Abort since entry already exists
            return self.async_abort(reason="already_configured")

        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the Home Assistant app discovery."""
        if TYPE_CHECKING:
            assert self.url is not None

        if user_input is not None:
            return self._finish(self.token)

        self._set_confirm_only()
        return self.async_show_form(step_id="hassio_confirm")

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a zeroconf discovery for a Music Assistant server."""
        try:
            # Parse zeroconf properties (strings) to ServerInfoMessage
            server_info = _parse_zeroconf_server_info(discovery_info.properties)
        except LookupError, KeyError, ValueError:
            return self.async_abort(reason="invalid_discovery_info")

        if (
            server_info.schema_version >= HASSIO_DISCOVERY_SCHEMA_VERSION
            and server_info.homeassistant_addon
        ):
            LOGGER.debug("Ignoring HA app server in zeroconf discovery")
            return self.async_abort(reason="already_discovered_addon")

        self.url = server_info.base_url
        self.server_info = server_info

        if TYPE_CHECKING:
            assert self.url is not None

        await self.async_set_unique_id(server_info.server_id)
        self._abort_if_unique_id_configured(updates={CONF_URL: self.url})

        try:
            await _get_server_info(self.hass, self.url)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-confirmation of discovered server."""
        if TYPE_CHECKING:
            assert self.url is not None
            assert self.server_info is not None

        if user_input is not None:
            if self.server_info.schema_version >= AUTH_SCHEMA_VERSION:
                return await self.async_step_auth()

            return self._finish(None)

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"url": self.url},
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle authentication via redirect to MA login."""
        if TYPE_CHECKING:
            assert self.url is not None

        # Check if we're returning from the external auth step with a token
        if user_input is not None:
            if "error" in user_input:
                return self.async_abort(reason="auth_error")
            # OAuth2 callback sends token as "code" parameter
            if "code" in user_input:
                self.token = user_input["code"]
                return self.async_external_step_done(next_step_id="finish_auth")

        # Check if we can use external auth (redirect flow)
        try:
            redirect_uri = async_get_redirect_uri(self.hass)
        except RuntimeError:
            # No current request context or missing required headers
            return await self.async_step_auth_manual()

        # Use OAuth2 callback URL with JWT-encoded state
        state = _encode_jwt(
            self.hass, {"flow_id": self.flow_id, "redirect_uri": redirect_uri}
        )
        # Music Assistant server will redirect to:
        # {redirect_uri}?state={state}&code={token}
        params = urlencode(
            {
                "return_url": f"{redirect_uri}?state={state}",
                "device_name": "Home Assistant",
            }
        )
        login_url = f"{self.url}/login?{params}"
        return self.async_external_step(step_id="auth", url=login_url)

    async def async_step_finish_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish authentication after receiving token."""
        if TYPE_CHECKING:
            assert self.url is not None
            assert self.token is not None

        # Exchange session token for long-lived token
        # The login flow gives us a session token (short expiration)
        session = aiohttp_client.async_get_clientsession(
            self.hass, verify_ssl=self.verify_ssl
        )

        try:
            LOGGER.debug("Creating long-lived token")
            long_lived_token = await create_long_lived_token(
                self.url,
                self.token,
                "Home Assistant",
                aiohttp_session=session,
            )
            LOGGER.debug("Successfully created long-lived token")
        except TimeoutError, CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except (AuthenticationFailed, InvalidToken) as err:
            LOGGER.error("Authentication failed: %s", err)
            return self.async_abort(reason="auth_failed")
        except InvalidServerVersion as err:
            LOGGER.error("Invalid server version: %s", err)
            return self.async_abort(reason="invalid_server_version")
        except MusicAssistantClientException:
            LOGGER.exception("Unexpected exception during connection test")
            return self.async_abort(reason="unknown")

        return self._finish(long_lived_token)

    async def async_step_auth_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual token entry as fallback."""
        if TYPE_CHECKING:
            assert self.url is not None

        errors: dict[str, str] = {}

        if user_input is not None:
            self.token = user_input[CONF_TOKEN]
            try:
                # Test the connection with the provided token
                await _test_connection(
                    self.hass, self.url, self.token, self.verify_ssl
                )
            except CannotConnect:
                return self.async_abort(reason="cannot_connect")
            except InvalidServerVersion:
                return self.async_abort(reason="invalid_server_version")
            except AuthenticationFailed, InvalidToken:
                errors["base"] = "auth_failed"
            except MusicAssistantClientException:
                LOGGER.exception("Unexpected exception during manual auth")
                return self.async_abort(reason="unknown")
            else:
                return self._finish(self.token)

        return self.async_show_form(
            step_id="auth_manual",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            description_placeholders={"url": self.url},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when token is invalid or expired."""
        self.url = entry_data[CONF_URL]
        self.verify_ssl = entry_data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if TYPE_CHECKING:
            assert self.url is not None

        if user_input is not None:
            # Redirect to auth flow
            return await self.async_step_auth()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"url": self.url},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the server address or the TLS verification choice.

        The existing token is tried against the new address first, so a
        server that only moved keeps its token; a token the server no longer
        accepts sends the user through the authentication steps again.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self.url = user_input[CONF_URL]
            self.verify_ssl = user_input[CONF_VERIFY_SSL]
            try:
                server_info = await _get_server_info(
                    self.hass, self.url, self.verify_ssl
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidServerVersion:
                errors["base"] = "invalid_server_version"
            except MusicAssistantClientException:
                LOGGER.exception("Unexpected exception during reconfiguration")
                errors["base"] = "unknown"
            else:
                self.server_info = server_info
                await self.async_set_unique_id(server_info.server_id)
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                if server_info.schema_version < AUTH_SCHEMA_VERSION:
                    return self._finish(None)
                token = entry.data.get(CONF_TOKEN)
                if token:
                    try:
                        await _test_connection(
                            self.hass, self.url, token, self.verify_ssl
                        )
                    except (
                        AuthenticationRequired,
                        AuthenticationFailed,
                        InvalidToken,
                    ):
                        return await self.async_step_auth()
                    except CannotConnect:
                        errors["base"] = "cannot_connect"
                    except MusicAssistantClientException:
                        LOGGER.exception("Unexpected exception during reconfiguration")
                        errors["base"] = "unknown"
                    else:
                        return self._finish(token)
                else:
                    return await self.async_step_auth()

        suggested_values = user_input or {
            CONF_URL: entry.data[CONF_URL],
            CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, suggested_values
            ),
            errors=errors,
        )
