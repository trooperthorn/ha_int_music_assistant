"""Voice-play intents for Music Assistant.

Home Assistant's built-in HassMediaSearchAndPlay already searches
(media_player.search_media) and plays (media_player.play_media) on whatever
media_player the calling device's area resolves to - device/area targeting is
handled entirely by the Assist LLM tool-calling pipeline (see
homeassistant.helpers.llm), not by anything here. The one thing it doesn't do
is notice when a name matches something on more than one source and always
plays the first result.

Music Assistant's own URI scheme already encodes the source a result came
from (spotify://, tidal://, library://, ...), so telling those apart needs
nothing beyond the media_content_id the generic search_media service already
returns - no Music Assistant client access, no extra service, no config entry
resolution. HassMassSearchAndPlay below reuses the exact same generic
media_player domain services and area-matching as the built-in intent, and
only adds: when the top-matching name is found on more than one distinct
source, ask which one instead of guessing. HassMassPlayFromSource handles the
follow-up once the LLM (which asked the question in the first place, and
carries the conversation itself) supplies a chosen source.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import urlparse

from homeassistant.components.media_player.browse_media import BrowseMedia, SearchMedia
from homeassistant.components.media_player.const import (
    ATTR_MEDIA_FILTER_CLASSES,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    SERVICE_SEARCH_MEDIA,
    MediaClass,
    MediaPlayerEntityFeature,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
import voluptuous as vol

from .const import LOGGER

INTENT_MASS_SEARCH_AND_PLAY = "HassMassSearchAndPlay"
INTENT_MASS_PLAY_FROM_SOURCE = "HassMassPlayFromSource"

# a library:// item may already merge several backing providers behind one
# Music Assistant library entry; that's one source from the user's point of
# view, so it's never itself a reason to ask which one they meant
_LIBRARY_SCHEME = "library"

_SLOT_SCHEMA_BASE = {
    vol.Optional("media_class"): vol.In(
        [MediaClass.ARTIST, MediaClass.ALBUM, MediaClass.TRACK, MediaClass.PLAYLIST]
    ),
    # optional name/area/floor slots handled by the intent matcher, mirroring
    # HassMediaSearchAndPlay so the same device/area targeting applies here
    vol.Optional("name"): str,
    vol.Optional("area"): str,
    vol.Optional("floor"): str,
    vol.Optional("preferred_area_id"): str,
    vol.Optional("preferred_floor_id"): str,
}


def _source_of(item: BrowseMedia) -> str:
    """Return the Music Assistant provider domain a search result came from.

    Item uris are ``<provider>://<media_type>/<item_id>``, and when more than
    one instance of the same provider type is configured the provider part
    itself is instance-scoped (``tidal--Ah76MuMg``). The instance suffix is
    stripped here: for "which source is this on" purposes, two instances of
    the same provider are the same source.
    """
    scheme = urlparse(item.media_content_id).scheme or _LIBRARY_SCHEME
    return scheme.split("--", 1)[0]


def _match_target(
    hass: HomeAssistant, slots: dict[str, Any], assistant: str | None
) -> str:
    """Resolve the single media_player entity the request targets.

    Same constraints/preferences HassMediaSearchAndPlay uses: a name/area/
    floor slot narrows it, and preferred_area_id/preferred_floor_id (filled
    in by the LLM tool-calling pipeline from the calling device's area) pick
    the right one when nothing else does.
    """
    match_constraints = intent.MatchTargetsConstraints(
        name=slots.get("name", {}).get("value"),
        area_name=slots.get("area", {}).get("value"),
        floor_name=slots.get("floor", {}).get("value"),
        domains={MEDIA_PLAYER_DOMAIN},
        assistant=assistant,
        features=MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA,
        single_target=True,
    )
    match_result = intent.async_match_targets(
        hass,
        match_constraints,
        intent.MatchTargetsPreferences(
            area_id=slots.get("preferred_area_id", {}).get("value"),
            floor_id=slots.get("preferred_floor_id", {}).get("value"),
        ),
    )
    if not match_result.is_match:
        raise intent.MatchFailedError(
            result=match_result, constraints=match_constraints
        )
    return match_result.states[0].entity_id


async def _search(
    hass: HomeAssistant,
    context: Context,
    entity_id: str,
    search_query: str,
    media_class: str | None,
) -> Sequence[BrowseMedia]:
    """Run the generic search_media service and return its result list."""
    search_data: dict[str, Any] = {"search_query": search_query}
    if media_class:
        search_data[ATTR_MEDIA_FILTER_CLASSES] = [media_class]
    try:
        response = await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SEARCH_MEDIA,
            search_data,
            target={"entity_id": entity_id},
            blocking=True,
            context=context,
            return_response=True,
        )
    except HomeAssistantError as err:
        LOGGER.error("Error calling search_media: %s", err)
        raise intent.IntentHandleError(f"Error searching media: {err}") from err

    entity_response = cast(SearchMedia, response.get(entity_id)) if response else None
    if not entity_response or not entity_response.result:
        raise intent.IntentHandleError(f"No results found for {search_query}")
    return entity_response.result


async def _play(
    hass: HomeAssistant, context: Context, entity_id: str, item: BrowseMedia
) -> None:
    """Play a single search result via the generic play_media service."""
    try:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                "entity_id": entity_id,
                "media_content_id": item.media_content_id,
                "media_content_type": item.media_content_type,
            },
            blocking=True,
            context=context,
        )
    except HomeAssistantError as err:
        LOGGER.error("Error calling play_media: %s", err)
        raise intent.IntentHandleError(f"Error playing media: {err}") from err


class MassSearchAndPlayHandler(intent.IntentHandler):
    """Search Music Assistant and play; ask which source if it's ambiguous."""

    description = (
        "Searches Music Assistant for an artist, song, album, or playlist and "
        "plays it. If the name matches something on more than one source "
        "(for example Spotify and Tidal), it does not play anything and "
        "instead lists the sources found so the assistant can ask which one "
        "the user means."
    )
    intent_type = INTENT_MASS_SEARCH_AND_PLAY
    slot_schema = {  # noqa: RUF012
        vol.Required("search_query"): str,
        **_SLOT_SCHEMA_BASE,
    }
    platforms = {MEDIA_PLAYER_DOMAIN}  # noqa: RUF012

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        search_query = slots["search_query"]["value"]
        media_class = slots.get("media_class", {}).get("value")

        entity_id = _match_target(hass, slots, intent_obj.assistant)
        results = await _search(
            hass, intent_obj.context, entity_id, search_query, media_class
        )

        top_title = results[0].title
        cluster = [
            item for item in results if item.title.casefold() == top_title.casefold()
        ]
        sources = {_source_of(item) for item in cluster}

        response = intent_obj.create_response()
        if len(sources) <= 1:
            await _play(hass, intent_obj.context, entity_id, results[0])
            response.async_set_speech_slots({"media": results[0].as_dict()})
            return response

        # ambiguous across sources: don't guess, hand the options back so the
        # LLM can ask and call HassMassPlayFromSource once the user answers
        response.async_set_speech(
            f'I found "{top_title}" on more than one source: '
            f"{', '.join(sorted(sources))}. Which one would you like?"
        )
        response.async_set_speech_slots(
            {
                "search_query": search_query,
                "title": top_title,
                "sources": sorted(sources),
            }
        )
        return response


class MassPlayFromSourceHandler(intent.IntentHandler):
    """Play the top match for a search, restricted to one named source."""

    description = (
        "Plays a previously searched Music Assistant artist, song, album, or "
        "playlist from a specific named source (for example Spotify, Tidal, "
        "or library), after HassMassSearchAndPlay asked which source the "
        "user meant."
    )
    intent_type = INTENT_MASS_PLAY_FROM_SOURCE
    slot_schema = {  # noqa: RUF012
        vol.Required("search_query"): str,
        vol.Required("source"): str,
        **_SLOT_SCHEMA_BASE,
    }
    platforms = {MEDIA_PLAYER_DOMAIN}  # noqa: RUF012

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        search_query = slots["search_query"]["value"]
        source = slots["source"]["value"].strip().casefold()
        media_class = slots.get("media_class", {}).get("value")

        entity_id = _match_target(hass, slots, intent_obj.assistant)
        results = await _search(
            hass, intent_obj.context, entity_id, search_query, media_class
        )

        matches = [item for item in results if _source_of(item).casefold() == source]
        if not matches:
            raise intent.IntentHandleError(
                f'No result for "{search_query}" found on {source}'
            )

        await _play(hass, intent_obj.context, entity_id, matches[0])
        response = intent_obj.create_response()
        response.async_set_speech_slots({"media": matches[0].as_dict()})
        return response


def async_setup_intents(hass: HomeAssistant) -> None:
    """Register the Music Assistant voice-play intents."""
    intent.async_register(hass, MassSearchAndPlayHandler())
    intent.async_register(hass, MassPlayFromSourceHandler())
