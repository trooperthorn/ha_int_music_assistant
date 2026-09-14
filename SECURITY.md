# Security Policy

## Reporting a vulnerability

Do not open a public issue containing exploit details, tokens, private
addresses, or logs. Use GitHub's private vulnerability-reporting feature for
this repository. If private reporting is unavailable, open a minimal issue
asking the maintainer to establish a private channel; omit technical details.

Include the affected version or commit, prerequisites, impact, a minimal
reproduction, and suggested remediation. Remove access tokens, server
addresses, and account names.

## Response targets

These are project targets, not an SLA: acknowledge critical and high reports
in three business days, establish severity and containment in seven, and
publish a coordinated fix as soon as it is safely validated. Lower-severity
issues are prioritized by exploitability and impact.

## Supported version

Only the latest published release and the default branch receive security
fixes. Operators should update Home Assistant and this integration promptly
and retain a tested rollback or backup.

## Security boundaries

The integration holds a long-lived Music Assistant access token in the config
entry, which Home Assistant stores unencrypted on disk. Anyone who can read
that file, or call this integration's actions, has the same authority on the
server as the token: playback control, library reads, and searches on behalf
of Music Assistant users when a `username` is given. The integration does not
harden the server, the network, or the Home Assistant host.

Certificate verification for HTTPS servers is a per-entry choice. Entries
created by the core integration, and entries created before this fork added
the choice, run without verification until reconfigured; see
`docs/security.md` for the reasoning and the migration path.
