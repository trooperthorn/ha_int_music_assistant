# Backlog

Dated open items.

## 2026-09-13

- Expose the `sync_adjust` (audio delay) player option that the
  library-manager frontend surfaces per player as a `number` entity. Needs
  the option's translation key confirmed against the server's player
  provider output, then an entry in `number.py`'s `PLAYER_OPTIONS_NUMBER`
  and `strings.json`.
- `music-assistant-client` 1.5.1 speaks API schema 46; the server is at 72.
  Track the client's releases and raise the pin when a newer client is
  published, re-running the suite (the mocks are typed against the client).
- The media browser fetches the first 500 items of every library section
  because Home Assistant's browser has no paging. If core adds paging, use
  it.
- Live verification against the El Rancho Assist instance: install through
  HACS, confirm the override loads, confirm the reconfigure flow and the
  configuration URL against the app on port 8094. Not done in the first
  pass; recorded in the README as the state of testing.
- GitHub App private key for zero-touch version bumps: Sean sets
  `RELEASE_AUTOMATION_PRIVATE_KEY` himself; until then the bump PR is manual.
