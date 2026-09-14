# Security

Trust boundaries, the certificate verification choice, and what stays
advisory. The reporting policy is in the repository's `SECURITY.md`.

## Trust boundaries

| Party | Can do | Through |
|---|---|---|
| Music Assistant server | Push any player, queue, and provider state; the integration trusts it as the source of truth and renders whatever names, uris, and image URLs it sends. | WebSocket events |
| Anyone with the long-lived token | Everything the integration can do on the server, including searches and playback on behalf of named Music Assistant users. | The config entry on disk (`.storage/core.config_entries`, unencrypted) |
| Home Assistant users with action access | Playback, queue transfer, library reads, searches; the `username` fields impersonate a server user for provider filtering only. | Actions and entity services |
| Home Assistant app discovery | Supplies the URL and token for a server running as an app; the flow trusts it because the Supervisor delivers it. | `async_step_hassio` |

The integration validates action input and rejects entity ids that are not
its own before anything reaches the server. It does not rate-limit, audit,
or authorize beyond what Home Assistant's own policy enforces.

## Certificate verification

Core creates the client session with `verify_ssl=False`, so an HTTPS server
URL is accepted with any certificate, and a network position between Home
Assistant and the server could read the token. This fork stores a
`verify_ssl` boolean per entry:

- New entries default to verification on. The setup form explains when to
  turn it off (a self-signed certificate the operator trusts).
- Entries created by core, or by this fork before the option existed, carry
  no value and are treated as verification off, so an existing self-signed
  setup does not break on upgrade. The reconfigure form shows the effective
  value and lets the operator turn it on.
- Plain HTTP servers, which is how most local installations and the Home
  Assistant app run, are unaffected either way.

This is enforced (the session is built from the stored value in
`async_setup_entry` and every config flow lookup), not cosmetic.

## Diagnostics redaction

`diagnostics.py` redacts the access token and the `identifiers` and
`manufacturer_id` maps of every player (MAC addresses and serial numbers)
and any `ip_address` field. Server URLs, player names, provider names, and
queue names are kept because they are what a support reader needs.

## Advisory findings kept as they are

- The browser login redirect signs its state with `_encode_jwt` from core's
  OAuth2 helper. That is core's mechanism and changing it means a different
  login protocol on the server; it stays.
- The `username` fields on actions let any Home Assistant user with action
  access act as any server user for the purpose of provider filtering. The
  server, not the integration, decides whether the token may impersonate;
  the integration only forwards the name.
- Image URLs and media source URLs come from the server and are written to
  entity attributes unchanged; the frontend fetches them. A malicious server
  could point them anywhere, but a malicious server already controls
  everything the integration shows.
