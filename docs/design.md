# Design

How the integration is put together and why the fork changed what it
changed. The audit that motivated the fork is `upstream_findings.md`;
operational facts live in `operations.md`; dated choices in `decisions.md`.

## Origin and relationship to core

The code started as a verbatim copy of `homeassistant/components/music_assistant`
at core tag 2026.9.1 (`iot_class` `local_push`, `integration_type` `service`).
The domain is kept so that a HACS download overrides the core copy in place:
entity ids, unique ids, device identifiers, action names, and the hassio and
zeroconf discovery paths are unchanged, and removing the custom copy returns
the user to core without migration. Upstream comments in the copied code are
left as they are so that a diff against core stays reviewable when core
moves; new code follows the house rule of explaining why in these documents
rather than in comments.

## Client lifecycle

`async_setup_entry` builds one `MusicAssistantClient` per entry on a shared
aiohttp session whose certificate verification follows the entry's
`verify_ssl` value. `connect()` runs under a ten second timeout and each
failure class maps to a distinct outcome:

- `CannotConnect`, `TimeoutError`, `MusicAssistantClientException`:
  `ConfigEntryNotReady` (core retries with backoff), and the connection loss
  is logged once.
- `InvalidServerVersion`: a repair issue plus `ConfigEntryNotReady`; the issue
  is deleted on the next successful connect.
- `AuthenticationRequired`, `AuthenticationFailed`, `InvalidToken`:
  `ConfigEntryAuthFailed`, unless the server runs as the Home Assistant app,
  where the app discovery will deliver a fresh token and reload the entry, so
  the entry waits in `ConfigEntryError` instead of asking the user.

The listen task (`_client_listen`) is what receives events. Setup waits up to
thirty seconds for the client to signal that its initial state is loaded,
then forwards the platforms. If the listener dies after the entry is loaded,
the loss is logged once and the entry is reloaded, which reconnects through
the retry path above. `hass.data[DOMAIN]` holds only the set of entry ids
whose loss has been logged, so the "restored" message is written exactly
once per outage; per-entry state stays in `entry.runtime_data`.

## Data update model

The integration is push only. The client keeps the full player, queue, and
provider state in memory and emits typed events; entities subscribe to
`PLAYER_UPDATED` for their own player id, to `QUEUE_UPDATED` (filtered in the
callback to the queue that feeds the player), and option entities to
`PLAYER_OPTIONS_UPDATED`. `PLAYER_ADDED`, `PLAYER_REMOVED`, and the
`expose_to_ha` toggle inside `PLAYER_CONFIG_UPDATED` add and remove devices.
No polling occurs, which is why every platform declares
`PARALLEL_UPDATES = 0`: there are no updates to serialize, and the server
handles concurrent commands itself.

At each setup the player configs are fetched once to remove devices whose
players disappeared while Home Assistant was disconnected.

## Entity model

`MusicAssistantEntity` owns the device record (`player_device_info`), the
player id as unique id, availability (player known, player available, socket
connected), and the event subscriptions. `MusicAssistantPlayerOptionEntity`
adds the option key and the `PLAYER_OPTIONS_UPDATED` subscription for the
number, select, switch, and text platforms, which create an entity only for
option translation keys they know, so an unknown option never produces an
entity with an untranslated name.

The media player maps the server's playback state, source and sound mode
lists (passive entries hidden), group membership (resolved to entity ids),
volume (group volume for group players), and the current media. The
`media_content_type` follows the media type of the current item; the device
class follows the server icon for TV-shaped players; the icon is refreshed
when the player configuration changes.

The device record carries the manufacturer, model, model id, firmware
version, MAC address (as a device connection), and serial number the server
reports, and a configuration URL built from the server's browser-reachable
address (`external_url`, then `base_url`, then the connection URL), because
the address the integration connects to may be an internal-only port.

## Browse and search

`media_browser.py` builds the root listing (seven library sections plus the
Home Assistant media sources), one listing per section, and item listings
for artists, albums, and playlists. Items are identified by the server's
`provider://type/id` uris; `uri_media_type()` parses that shape and is the
only way an item is routed, so a uri whose id happens to contain the word
`artist` cannot be mistaken for an artist. In-place search inside an album
or playlist filters that container's tracks locally; inside an artist it
runs a server search prefixed with the artist name and limited to albums
and tracks.

## Actions

Six actions are registered in `async_setup`: two entry-scoped
(`search`, `get_library`, keyed by `config_entry_id`) and four entity
platform actions (`play_media`, `play_announcement`, `transfer_queue`,
`get_queue`). Entity ids given to `transfer_queue` and to the standard
`join` action are resolved through `get_player_id_for_entity()`, which
accepts only this integration's entities. Every error path raises a
`ServiceValidationError` (user input) or `HomeAssistantError` (server
failure) with a translation key from `strings.json`; server exceptions are
wrapped by `catch_musicassistant_error` with the server's message as a
placeholder.

## Config flow

The user, zeroconf, and hassio paths converge on `_finish()`, which writes
the URL, the certificate choice, and the token (when the server requires
one) and either creates the entry or updates the entry under reauth or
reconfigure. The browser login redirect is core's mechanism unchanged; the
manual token form is the fallback when Home Assistant cannot build a
redirect URL. Reconfigure tries the stored token against the new address
first so a server that only moved does not force a new login, and refuses an
address that answers with a different server id.

## Testing

The suite is core's suite ported to `pytest-homeassistant-custom-component`
(fixtures under `tests/fixtures`, snapshots under `tests/snapshots` with the
harness's Home Assistant serializer applied explicitly in `conftest.py`),
plus `test_rework.py`, `test_init_lifecycle.py`, and `test_diagnostics.py`
for the behaviour this fork changed. The 31 entity snapshots are byte for
byte the core ones, which is the proof that the rework changed no entity
state or registry attribute a dashboard could depend on.
