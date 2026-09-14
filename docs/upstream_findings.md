# Audit of the core Music Assistant integration

Source: `homeassistant/components/music_assistant` at core tag 2026.9.1
(quality scale declared `bronze`, requirement `music-assistant-client==1.5.1`,
client API schema 46 against a current server at schema 72). Every finding
was confirmed by reading the code and, where the fix is in this fork, by a
regression test named in the last column. Severity is what a user would see:
**high** breaks a feature or corrupts a command, **medium** produces a wrong
result in a reachable case, **low** is cosmetic or defensive.

## Defects

| # | Severity | Where (core) | What is wrong | Fork | Test |
|---|---|---|---|---|---|
| 1 | high | `media_browser.py` `async_browse_media`, `async_search_media`, `_get_media_types_from_query` | Items are routed by `"artist" in media_content_id`, `"album/" in ...`, `"playlist/" in ...`. A uri such as `spotify://playlist/artist-mix` matches `artist` first and is browsed as an artist (calls `get_artist_albums` on a playlist); any track or playlist whose id contains `album` is misrouted too. Searching inside a playlist whose uri contains `artist` narrows the media types to albums and tracks. | Parse `provider://type/id` with `uri_media_type()`; bare names still work for compatibility. | `test_uri_media_type`, `test_browse_playlist_named_like_an_artist` |
| 2 | medium | `services.py` `get_library` schema | `vol.Optional(ATTR_ALBUM_TYPE): list[MediaType]` is a type annotation, not a validator; voluptuous treats the generic alias as a plain `list` check, so any strings pass through unvalidated and the annotation names the wrong enum (album types are `AlbumType`, not `MediaType`). The selector also lacked `live` and `soundtrack`, which the enum has. | `vol.In` over `AlbumType` values; selector and translations extended. | `test_get_library_validates_album_type` |
| 3 | medium | `media_player.py` `async_set_volume_level` | `int(volume * 100)` truncates: 0.29 * 100 is 28.999... and the server receives 28. Every level whose float product lands just below the integer is off by one. | `round()`. | `test_volume_set_rounds_to_nearest_percent` |
| 4 | medium | `media_player.py` `async_play_media` | `kwargs[ATTR_MEDIA_EXTRA]` raises `KeyError` when a caller invokes the entity method directly without `extra` (the service layer always supplies it; other integrations and scripts calling the entity do not). | `kwargs.get(ATTR_MEDIA_EXTRA) or {}`. | `test_play_media_without_extra` |
| 5 | medium | `media_player.py` `async_join_players`, `_async_handle_transfer_queue` | Any registered entity id is accepted and its `unique_id` is sent to the server as a Music Assistant player id. A Sonos or Cast entity's unique id is not a player id, so the server rejects it with an opaque error or, if it collides, groups the wrong player. | `get_player_id_for_entity()` checks the entity belongs to this integration and raises a translated `ServiceValidationError`. | `test_transfer_queue_rejects_foreign_entity`, updated join test |
| 6 | medium | `media_player.py` `async_set_shuffle`, `async_set_repeat`, `async_clear_playlist` | Without an active queue the commands return silently; the user sees success while nothing happened. Violates the Silver `action-exceptions` rule. | `_require_active_queue()` raises `no_active_queue`. | `test_queue_actions_raise_without_active_queue` |
| 7 | medium | `entity.py` `__init__` | `configuration_url` is built from `mass.server_url`, the address the integration connects to. For the Home Assistant app that is the internal-only webserver on port 8094 (`config_flow.py` comment), which no browser can open. The server reports `external_url` and `base_url` in its server info since schema 32. | `player_configuration_url()` prefers `external_url`, then `base_url`, then the connection URL. | `test_device_info_uses_browser_reachable_url` |
| 8 | medium | `__init__.py` `async_setup_entry` | Whole integration uses `async_get_clientsession(hass, verify_ssl=False)`: certificate verification is disabled for every HTTPS server with no way to turn it on. | `verify_ssl` stored per entry; new entries default to verify, old entries keep the old behaviour until reconfigured. | `test_setup_uses_verify_ssl_from_entry`, `test_user_flow_passes_verify_ssl_choice` |
| 9 | low | `entity.py` `available` | `self.player` indexes `mass.players[player_id]` and raises `KeyError` when the server has already dropped the player but the device removal has not run yet; a state write in that window fails. | `available` uses `players.get()`; the update callback returns early when the player is gone. | covered by the player removal test |
| 10 | low | `entity.py` `__init__` | `provider = mass.get_provider(...)` may return `None` when the provider instance is unavailable; only a `TYPE_CHECKING` assert guards it, so `provider.name` raises `AttributeError` at runtime. | Falls back to the provider id. | `player_device_info` |
| 11 | low | `__init__.py` `async_remove_config_entry_device` | Calls `get_music_assistant_client()`, which raises `ServiceValidationError` when the entry is not loaded; the device registry expects a boolean. | Returns `False` when the entry is not loaded. | `test_remove_device_when_entry_not_loaded` |
| 12 | low | `__init__.py` `async_setup_entry` | When the listen task has already failed, the code calls `async_unload_platforms` before the platforms were ever forwarded. Harmless today, misleading and one core change away from a warning. | Removed; the client is disconnected and `ConfigEntryNotReady` raised. | `test_listen_fails_before_ready_retries` |
| 13 | low | `media_player.py` `__init__` | `_attr_icon` is computed once from the player icon; changing the icon in the server's player settings never reaches Home Assistant until a restart. Device class is always `speaker`, and `media_content_type` is always `music` even for podcasts. | Icon refreshed on `PLAYER_CONFIG_UPDATED`; TV icons map to the TV device class; content type follows `current_media.media_type`. | snapshot tests |
| 14 | low | `const.py`, `media_browser.py` | `ATTR_STREAM_TITLE` defined twice; `DOMAIN_EVENT`, `ATTR_IS_GROUP`, `ATTR_GROUP_MEMBERS`, `ATTR_GROUP_PARENTS`, `PLAYABLE_MEDIA_TYPES` (with `PODCAST` listed twice) are unused. | Removed. | ruff |
| 15 | low | `helpers.py`, `media_player.py`, `services.py` | Error strings are untranslated English (`"Entry not found"`, `"No active queue found"`, `f"Unsupported media type ..."`), against the Gold `exception-translations` rule. | Every raised error has a key in `strings.json` and `translations/en.json`. | `test_*_translated` |
| 16 | low | `entity.py` | The device record omits the MAC address, serial number, model id, and firmware version the server provides in `player.device_info`. | Added; MAC becomes a device connection. | `test_device_info_carries_hardware_identifiers` |

## Quality scale gaps in core (declared `todo`)

| Rule | Tier | Core state | Fork |
|---|---|---|---|
| `action-exceptions` | Silver | Queue commands return silently (defect 6). | done |
| `log-when-unavailable` | Silver | Connection loss is logged at error level on every drop; nothing marks the return. | Logged once at info on loss, once on return, tracked per entry in `hass.data`. |
| `parallel-updates` | Silver | Not declared on any platform. | `PARALLEL_UPDATES = 0` on all six. |
| `test-coverage` | Silver | Not declared. | 97 percent measured (`pytest --cov`). |
| `diagnostics` | Gold | Absent. | `diagnostics.py`. |
| `docs-data-update` | Gold | Not written. | `design.md`, push model section. |
| `exception-translations` | Gold | Only `invalid_username`. | 18 keys. |
| `reconfiguration-flow` | Gold | Absent. | `async_step_reconfigure`. |

The three Platinum rules (`async-dependency`, `inject-websession`,
`strict-typing`) were already met by core; mypy strict passes on the fork.

## Comparison with the trooperthorn frontend fork and app

The library-manager frontend (`HA_int_MA-UI`) and the app that ships it
(`ha_app_music_assistant`) are pure server-side and browser-side products;
neither changes the WebSocket API the integration consumes, so nothing in
this fork depends on them. Three points where they touch:

- The app announces itself with the same `music_assistant` discovery slug,
  `ingress_port` 8094, and `host_network`, so the hassio discovery path in
  `config_flow.py` is exercised unchanged. Defect 7 matters most in that
  setup: with the app, `mass.server_url` is the ingress-only port.
- The fork's per-user hidden players and the `hide_in_ui` flag are separate
  from `expose_to_ha`; the integration keeps following `expose_to_ha` only,
  which is the server's contract.
- The frontend's `sync_adjust` per-player delay is a player option; the
  integration's number platform creates entities only for translation keys it
  knows, so a new option needs a key added in `number.py` and `strings.json`.
  Recorded in `backlog.md`.

## Not changed

- The 500-item first page in every browse listing (the media browser has no
  paging) and the `"artist - album - name"` concatenation the search action
  uses to pass artist and album context to the server. Both are server
  interface limits, not integration defects.
- `_encode_jwt` is imported from `config_entry_oauth2_flow`, a private
  helper. It is how core does the redirect login; changing it means a
  different login mechanism.
- `music-assistant-client` stays at the exact pin core uses. It is not in
  core's `package_constraints.txt`, so an exact pin is safe (see the
  ha-dev-current contract on core-constrained requirements).
