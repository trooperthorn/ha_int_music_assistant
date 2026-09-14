# Music Assistant for Home Assistant (Platinum rework)

![GitHub Release](https://img.shields.io/github/v/release/trooperthorn/ha_int_music_assistant?style=for-the-badge)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.9.0-blue.svg?style=for-the-badge)

A custom integration that replaces the built-in `music_assistant` integration
with a version audited against the Home Assistant integration quality scale
and raised from Bronze to Platinum. It keeps the same domain, entity ids,
actions, and discovery, so installing it changes nothing in your dashboards
and automations; it fixes the defects listed in
[docs/upstream_findings.md](docs/upstream_findings.md) and adds the missing
Silver, Gold, and Platinum rules (diagnostics, a reconfigure flow, translated
errors, parallel-update limits, unavailability logging, and test coverage
above 95 percent).

*This is a community-developed integration and is not affiliated with the
Music Assistant project or the Open Home Foundation.*

## What changed against core

Fixes, each with a regression test:

- The browse tree and in-place search routed items by looking for the words
  `artist`, `album`, and `playlist` anywhere in the item uri, so a playlist or
  track whose uri contained one of those words was browsed as the wrong type.
  Routing now parses the `provider://type/id` uri.
- Setting the volume truncated the percentage (0.29 became 28); it now rounds.
- A direct `async_play_media` call without the `extra` mapping raised
  `KeyError`; the mapping is now optional, as the media player contract says.
- `join` and `transfer_queue` accepted any entity id and forwarded that
  entity's unique id to the server as a player id; entities of other
  integrations are now rejected with a translated error.
- Shuffle, repeat, and clear playlist silently did nothing without an active
  queue; they now raise a translated `ServiceValidationError`.
- `get_library`'s `album_type` field used a type annotation as its validator,
  so nothing was validated; it now validates against the server's album types
  and offers the two (live, soundtrack) the selector lacked.
- The device configuration URL pointed at the address the integration
  connects to, which for the Home Assistant app is the internal-only port 8094
  webserver; it now uses the browser-reachable address the server reports.
- The device record gains the MAC address, serial number, model id, and
  firmware version the server already provides.
- Player icons update when the player configuration changes, TV-shaped players
  get the TV device class, and `media_content_type` reflects podcasts and
  playlists instead of always reporting music.
- Removing a device while the entry is not loaded no longer raises a service
  error out of the device registry.
- An entity whose player was removed from the server no longer raises
  `KeyError` from its availability check between the removal event and the
  device cleanup.

Additions for the quality scale:

- `diagnostics.py` with the token and hardware identifiers redacted.
- A reconfigure flow for the server address and certificate verification that
  keeps the existing token when the server still accepts it.
- A `verify_ssl` choice in the setup and reconfigure forms. Core disabled
  certificate verification for every connection; new entries verify by
  default, and entries created before this change keep the old behaviour
  until reconfigured (see [docs/security.md](docs/security.md)).
- Every error a user can see carries a translation key; the config entry
  setup errors do too.
- The loss and return of the server connection are logged once each at info
  level.
- `PARALLEL_UPDATES = 0` on every platform, matching the push-based design.

## Requirements

- Home Assistant 2026.9.0 or newer on Python 3.14.
- A Music Assistant server, either the official app, the
  [trooperthorn library-manager app](https://github.com/trooperthorn/ha_app_music_assistant),
  or a standalone server with API schema 28 or newer (Music Assistant 2.4).

## Installation

### HACS

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add this repository's URL, category **Integration**.
4. Search for **Music Assistant (Platinum rework)**, click **Download**, then
   restart Home Assistant.

HACS warns that the download overrides a built-in integration. That is the
intent: a custom integration with the same domain takes precedence over the
core copy, and removing it restores the core copy after a restart.

### Manual

1. Download `music_assistant.zip` from the latest release and verify it
   (see Releases below).
2. Extract it into `custom_components/music_assistant` in your configuration
   directory.
3. Restart Home Assistant.

### Setup

An existing Music Assistant config entry keeps working unchanged. For a new
server, go to **Settings > Devices & Services > Add Integration**, search for
**Music Assistant**, enter the server URL and whether to verify its
certificate, and complete the login the server opens in your browser. Servers
running as a Home Assistant app are discovered automatically.

Afterwards **Reconfigure** on the entry changes the address or the
certificate choice without removing the entry.

## What it creates

Platform | What
---|---
`media_player` | One entity per player the server exposes to Home Assistant, with play, pause, stop, seek, volume, mute, power, shuffle, repeat, grouping, source and sound mode selection, browse, search, and announcements.
`button` | Favorite the item that is playing.
`number`, `select`, `switch`, `text` | Player options the server publishes (bass, treble, sound field, sleep timer, and so on); the less common ones are disabled by default.

Actions: `music_assistant.play_media`, `play_announcement`, `transfer_queue`,
`get_queue`, `search`, and `get_library`, unchanged from core.

## Releases

A merge to `main` publishes a release carrying `music_assistant.zip`, an SPDX
SBOM, `SHA256SUMS`, and provenance and SBOM attestations. Verify a download
with:

```bash
gh release download <tag> -R trooperthorn/ha_int_music_assistant -p music_assistant.zip -p SHA256SUMS
sha256sum --check SHA256SUMS --ignore-missing
gh attestation verify music_assistant.zip -R trooperthorn/ha_int_music_assistant
```

## Development

The gate is `ruff check .`, `mypy --config-file mypy.ini
custom_components/music_assistant`, and `pytest tests/`; pins are in
`requirements-dev.txt`. The test harness imports `fcntl`, so on Windows run
the suite under WSL. See [docs/operations.md](docs/operations.md).

Documentation index: [docs/README.md](docs/README.md).
