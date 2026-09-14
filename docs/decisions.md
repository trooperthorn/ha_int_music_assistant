# Decisions

Dated decisions with the alternative rejected and why.

## 2026-09-13, keep the `music_assistant` domain and override core

The fork keeps core's domain so a HACS download replaces the built-in copy
in place: no entity id, unique id, device, action, or discovery changes, and
uninstalling returns the user to core. Rejected: a new domain such as
`music_assistant_lm`. It would avoid the HACS override warning but would
create a second set of entities for the same players, break the app's
hassio discovery (which targets the `music_assistant` domain), and force
every dashboard and automation to be edited. The override warning is
accurate and the README says so.

## 2026-09-13, upstream comments stay, new code explains itself in docs

House rule is that code carries only what a reader needs at the point of
reading. Core's copy carries longer comments (the addon port explanation in
the hassio step, the pause-feature rationale, the username impersonation
note). They are left as they are, because the value of a small diff against
core when folding in the next monthly release outweighs the density rule,
which yamaha_ynca already applies to upstream code. Everything the fork
added explains itself in `design.md`, `security.md`, and this file.

## 2026-09-13, `verify_ssl` defaults differ for new and existing entries

Core connects with `verify_ssl=False` for everyone. Making verification the
default for existing entries would break every HTTPS setup with a
self-signed certificate on upgrade, with a config entry error and no clear
path. New entries default to on; entries without the key are treated as off
and can be switched on through reconfigure. Rejected: a repair issue for
every entry without the key. Most installations use plain HTTP or the app,
where the flag does nothing, so the issue would be noise for the majority.

## 2026-09-13, reconfigure tries the existing token first

A moved server (new IP, new port, HTTPS turned on) almost always keeps its
token store, so the reconfigure step tests the stored token against the new
address and only sends the user through the login steps when the server
rejects it. Rejected: always re-authenticating on reconfigure, which is
simpler but makes the common case (an address change) a full login.

## 2026-09-13, connection loss bookkeeping lives in `hass.data[DOMAIN]`

The Silver rule asks for one log line when the connection is lost and one
when it returns. `entry.runtime_data` is recreated on every setup attempt,
so it cannot remember that a loss was already logged across the retries
`ConfigEntryNotReady` triggers. A set of entry ids in `hass.data[DOMAIN]` is
the smallest cross-attempt state; it is cleared by `async_remove_entry`.
Rejected: relying on core's own "retrying setup" warning, which is logged
once by core but never marks the return.

## 2026-09-13, `PARALLEL_UPDATES = 0` everywhere

The integration never polls; all state arrives by event, and the server
serializes commands per player itself. Zero is the honest declaration.
Rejected: `1` on the action platforms, which would queue Home Assistant
side commands behind each other for no benefit.

## 2026-09-13, entity ids given to join and transfer must be this integration's

Core forwarded any entity's unique id to the server. Rejected: silently
skipping foreign entities, which hides a user mistake; the translated
validation error names the entity instead.

## 2026-09-13, bare media type names still browse

Only the tests pass `artist`, `album`, or `playlist` as a bare
`media_content_id`; the browse tree always emits full uris. The fallback
costs one enum lookup and keeps core's tests passing unchanged, which is
what proves the routing rewrite did not change the reachable behaviour.

## 2026-09-13, how the core tests were ported

`tests.common` and `tests.typing` become the harness modules of the same
name; `homeassistant.components.music_assistant` becomes
`custom_components.music_assistant` in imports and patch targets; fixture
loads drop the integration argument because the harness resolves
`tests/fixtures` from the calling test file (and `async_load_fixture` cannot
be used, because it resolves the path from an executor thread); the harness
snapshot extension is applied in `conftest.py`. Recorded so the next core
merge can repeat it mechanically.

## 2026-09-13, scanner findings that do not apply

`check_stale.py` flags `async_update_reload_and_abort` under the 2026.12
"update listener plus reload" rule; this integration registers no update
listener, so the reload-in-flow stays. The `hacs` minimum-version key is
documented in hacs-documentation `publish/start.md` and stays.
