"""Helpers for the Music Assistant integration."""

from collections.abc import Callable, Coroutine, Generator
from contextlib import contextmanager
import functools
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from music_assistant_models.errors import MusicAssistantError, UserNotFoundError

from .const import DOMAIN

if TYPE_CHECKING:
    from music_assistant_client import MusicAssistantClient

    from . import MusicAssistantConfigEntry


def catch_musicassistant_error[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Convert a Music Assistant server error into a translated HA error."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        """Catch Music Assistant errors and convert to Home Assistant error."""
        try:
            return await func(*args, **kwargs)
        except MusicAssistantError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="server_error",
                translation_placeholders={"error": str(err) or err.__class__.__name__},
            ) from err

    return wrapper


@contextmanager
def catch_user_not_found(username: str | None) -> Generator[None]:
    """Convert a server UserNotFoundError into a translated invalid_username error."""
    if username is None:
        yield
        return
    try:
        yield
    except UserNotFoundError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_username",
            translation_placeholders={"username": username},
        ) from err


@callback
def get_music_assistant_client(
    hass: HomeAssistant, config_entry_id: str
) -> MusicAssistantClient:
    """Get the Music Assistant client for the given config entry."""
    entry: MusicAssistantConfigEntry | None
    if not (entry := hass.config_entries.async_get_entry(config_entry_id)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"config_entry_id": config_entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    return entry.runtime_data.mass


@callback
def get_player_id_for_entity(hass: HomeAssistant, entity_id: str) -> str:
    """Resolve a Music Assistant media_player entity id to its player id.

    The unique id of every media_player entity this integration creates is
    the Music Assistant player id; entities of any other integration are
    rejected instead of having their unrelated unique id passed to the server.
    """
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(entity_id)
    if entry is None or entry.platform != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entity_not_music_assistant",
            translation_placeholders={"entity_id": entity_id},
        )
    return entry.unique_id
