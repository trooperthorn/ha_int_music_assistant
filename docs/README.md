# Documentation index

One line per document stating what it owns, so a reader knows where a fact
belongs. Code carries only what a reader needs at the point of reading;
explanation lives here.

- `upstream_findings.md`: the audit of the core `music_assistant` integration
  at Home Assistant 2026.9.1 that this fork started from: every defect, its
  severity, where it lives, and what this fork did about it, plus the quality
  scale gaps.
- `design.md`: how the integration is put together (client lifecycle, event
  fan-out, entity model, browse and search, actions) and the reasoning behind
  the changes made here.
- `security.md`: trust boundaries, the certificate verification choice, what
  diagnostics redact, and the findings that stay advisory.
- `operations.md`: the test gate, the release path, branch protection, and
  how to keep the fork current with core.
- `decisions.md`: dated decisions with the alternative rejected and why.
- `backlog.md`: dated open items.
