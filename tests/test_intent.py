"""Test the Music Assistant voice-play intents."""

from unittest.mock import AsyncMock, MagicMock, call

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
from music_assistant_models.errors import MusicAssistantError
from music_assistant_models.media_items import SearchResults, Track
import pytest

from custom_components.music_assistant.intent import (
    INTENT_MASS_PLAY_FROM_SOURCE,
    INTENT_MASS_SEARCH_AND_PLAY,
)

from .common import setup_integration_from_fixtures

TARGET_ENTITY_ID = "media_player.test_player_1"
TARGET_NAME = "Test Player 1"
TARGET_QUEUE_ID = "00:00:00:00:00:01"


def _play_media_call(uri: str):
    """Build the expected player_queues/play_media send_command call."""
    return call(
        "player_queues/play_media",
        queue_id=TARGET_QUEUE_ID,
        media=[uri],
        option=None,
        radio_mode=False,
        start_item=None,
        username=None,
        sort_by=None,
    )


def _track(uri: str, name: str = "Tennessee Whiskey") -> Track:
    """Build a minimal, available Track for search-result mocking."""
    provider = uri.split("://", 1)[0]
    item_id = uri.rsplit("/", 1)[-1]
    return Track.from_dict(
        {
            "item_id": item_id,
            "provider": provider,
            "name": name,
            "version": "",
            "sort_name": name.lower(),
            "uri": uri,
            "media_type": "track",
            "provider_mappings": [
                {
                    "item_id": item_id,
                    "provider_domain": provider.split("--", 1)[0],
                    "provider_instance": provider,
                    "available": 1,
                    "audio_format": {},
                }
            ],
            "metadata": {},
            "favorite": False,
            "position": None,
            "duration": 200,
            "artists": [],
        }
    )


@pytest.fixture(autouse=True)
async def _setup(hass: HomeAssistant, music_assistant_client: MagicMock) -> None:
    """Set up the integration with fixture players before each test."""
    await setup_integration_from_fixtures(hass, music_assistant_client)


async def test_search_and_play_single_source_plays_immediately(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """A name found on exactly one source plays right away, no question asked."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(tracks=[_track("library://track/456")])
    )

    response = await intent.async_handle(
        hass,
        "test",
        INTENT_MASS_SEARCH_AND_PLAY,
        {
            "search_query": {"value": "Tennessee Whiskey"},
            "name": {"value": TARGET_NAME},
        },
    )

    assert response.response_type == intent.IntentResponseType.ACTION_DONE
    assert music_assistant_client.send_command.call_args == _play_media_call(
        "library://track/456"
    )


async def test_search_and_play_multiple_sources_asks_instead_of_playing(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """A name found on two distinct sources asks, and does not play anything."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(
            tracks=[
                _track("spotify://track/1"),
                _track("tidal--Ah76MuMg://track/2"),
            ]
        )
    )

    response = await intent.async_handle(
        hass,
        "test",
        INTENT_MASS_SEARCH_AND_PLAY,
        {
            "search_query": {"value": "Tennessee Whiskey"},
            "name": {"value": TARGET_NAME},
        },
    )

    assert response.speech
    speech_text = response.speech["plain"]["speech"]
    assert "spotify" in speech_text
    assert "tidal" in speech_text
    assert music_assistant_client.send_command.call_count == 0


async def test_search_and_play_same_provider_two_instances_is_one_source(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """Two instances of the same provider type count as one source."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(
            tracks=[
                _track("tidal--Ah76MuMg://track/1"),
                _track("tidal--Zz99Other://track/2"),
            ]
        )
    )

    response = await intent.async_handle(
        hass,
        "test",
        INTENT_MASS_SEARCH_AND_PLAY,
        {
            "search_query": {"value": "Tennessee Whiskey"},
            "name": {"value": TARGET_NAME},
        },
    )

    assert response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_play_from_source_plays_the_matching_result(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """The follow-up intent plays only the result matching the chosen source."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(
            tracks=[
                _track("spotify://track/1"),
                _track("tidal--Ah76MuMg://track/2"),
            ]
        )
    )

    response = await intent.async_handle(
        hass,
        "test",
        INTENT_MASS_PLAY_FROM_SOURCE,
        {
            "search_query": {"value": "Tennessee Whiskey"},
            "source": {"value": "tidal"},
            "name": {"value": TARGET_NAME},
        },
    )

    assert response.response_type == intent.IntentResponseType.ACTION_DONE
    assert music_assistant_client.send_command.call_args == _play_media_call(
        "tidal--Ah76MuMg://track/2"
    )


async def test_play_from_source_no_match_raises(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """An unknown source raises instead of silently playing something else."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(tracks=[_track("spotify://track/1")])
    )

    with pytest.raises(intent.IntentHandleError):
        await intent.async_handle(
            hass,
            "test",
            INTENT_MASS_PLAY_FROM_SOURCE,
            {
                "search_query": {"value": "Tennessee Whiskey"},
                "source": {"value": "tidal"},
                "name": {"value": TARGET_NAME},
            },
        )


async def test_search_and_play_no_results_raises(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """No search results raises rather than reporting a silent success."""
    music_assistant_client.music.search = AsyncMock(return_value=SearchResults())

    with pytest.raises(intent.IntentHandleError):
        await intent.async_handle(
            hass,
            "test",
            INTENT_MASS_SEARCH_AND_PLAY,
            {
                "search_query": {"value": "Nothing Matches This"},
                "name": {"value": TARGET_NAME},
            },
        )


async def test_search_and_play_no_matching_target_raises(hass: HomeAssistant) -> None:
    """An unresolvable name/area raises instead of guessing a player."""
    with pytest.raises(intent.MatchFailedError):
        await intent.async_handle(
            hass,
            "test",
            INTENT_MASS_SEARCH_AND_PLAY,
            {
                "search_query": {"value": "Tennessee Whiskey"},
                "name": {"value": "No Such Player"},
            },
        )


async def test_search_and_play_media_class_filter_is_passed_through(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """The optional media_class slot narrows the underlying search."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(tracks=[_track("library://track/456")])
    )

    await intent.async_handle(
        hass,
        "test",
        INTENT_MASS_SEARCH_AND_PLAY,
        {
            "search_query": {"value": "Tennessee Whiskey"},
            "media_class": {"value": "track"},
            "name": {"value": TARGET_NAME},
        },
    )

    assert music_assistant_client.music.search.call_args.kwargs["media_types"] == [
        "track"
    ]


async def test_search_and_play_search_error_raises_intent_error(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """A HomeAssistantError from the search call surfaces as an intent error."""
    music_assistant_client.music.search = AsyncMock(
        side_effect=HomeAssistantError("boom")
    )

    with pytest.raises(intent.IntentHandleError):
        await intent.async_handle(
            hass,
            "test",
            INTENT_MASS_SEARCH_AND_PLAY,
            {
                "search_query": {"value": "Tennessee Whiskey"},
                "name": {"value": TARGET_NAME},
            },
        )


async def test_play_from_source_play_error_raises_intent_error(
    hass: HomeAssistant, music_assistant_client: MagicMock
) -> None:
    """A Music Assistant error while playing surfaces as an intent error."""
    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(tracks=[_track("spotify://track/1")])
    )
    music_assistant_client.send_command = AsyncMock(
        side_effect=MusicAssistantError("boom")
    )

    with pytest.raises(intent.IntentHandleError):
        await intent.async_handle(
            hass,
            "test",
            INTENT_MASS_PLAY_FROM_SOURCE,
            {
                "search_query": {"value": "Tennessee Whiskey"},
                "source": {"value": "spotify"},
                "name": {"value": TARGET_NAME},
            },
        )
