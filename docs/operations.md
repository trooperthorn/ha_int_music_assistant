# Operations

The test gate, the release path, and how to keep the fork current with
core. Design rationale is in `design.md`.

## Test gate

The gate is the same on a workstation and in CI: `ruff check .`, `mypy
--config-file mypy.ini custom_components/music_assistant`, `pytest -ra
--strict-markers tests/`, then `python scripts/build_release_artifacts.py
--validate-only`. Pins are in `requirements-dev.txt`;
`pytest-homeassistant-custom-component` 0.13.363 pins core 2026.9.0 itself,
so no separate core pin file is needed. The harness imports `fcntl`, so on
Windows the suite runs under WSL (a venv at `~/mavenv` was used for the
first pass). Coverage is measured with `pytest --cov=custom_components/music_assistant`
and was 97 percent at the first release.

Snapshot tests need the harness's Home Assistant serializer; syrupy's own
`snapshot` fixture shadows the harness copy, so `tests/conftest.py` applies
the extension explicitly and the files live in `tests/snapshots`.

## Release path

A merge to `main` is the only release path. Nobody edits the manifest
version or pushes a tag by hand.

1. `Release` runs on every push to `main`. It calls the Test and Validate
   workflows, reads the version from `custom_components/music_assistant/manifest.json`
   through `.release.json`, and stops if a published release for that
   version exists. Otherwise it creates the `v<version>` tag on the exact
   commit, drafts the GitHub release, and publishes it. HACS installs
   `custom_components/music_assistant` directly from that tagged repository
   tree; no ZIP release asset is required.
2. `Prepare release` runs after every successful `Release` on `main`. When
   the manifest version equals the latest published release and
   `custom_components/music_assistant` changed since that tag, it runs
   `scripts/set_version.py --next-from-tags`, pushes the bump to
   `automation/calver-release` with a GitHub App token, opens a PR, and arms
   squash auto-merge. Docs, tests, and workflow changes do not bump the
   version.
3. Without the GitHub App credentials (`RELEASE_AUTOMATION_CLIENT_ID`
   variable and `RELEASE_AUTOMATION_PRIVATE_KEY` secret) the second step
   stops at its credential check. The repository still releases: run
   `python scripts/set_version.py --next-from-tags` on a branch, open the
   PR, and the merge publishes.

Versions are `YYYY.MM.DD.N` in `America/Chicago`.

## Branch and protection settings

`main` is the only long-lived branch. Work happens on short-lived branches
that end in a squash-merged PR and are deleted on merge. Branch protection
requires the job display names `pytest (Python 3.14)`, `HACS validation`,
`hassfest (manifest sanity)`, `CodeQL (python)`, and `Python static security
checks`, with strict up-to-date checks, enforced for administrators, no
force pushes, no deletions, and no required approvals.

## Keeping current with core

Core's copy moves every month. To fold a core release in:

1. `git -C ~/repos/ha-core-reference` at the new tag; diff
   `homeassistant/components/music_assistant` against the previous tag.
2. Apply the upstream hunks to `custom_components/music_assistant`,
   keeping the fork's changes (listed in `upstream_findings.md`); the
   upstream comments are left in place for exactly this reason.
3. Copy the upstream tests and fixtures over `tests/`, re-run the import
   rewrite from `decisions.md` (2026-09-13), and run the gate. The 31 entity
   snapshots must still pass unchanged unless core changed an entity on
   purpose.
4. Raise `homeassistant` in `hacs.json` and the harness pin together.

## Line endings

`.gitattributes` pins every text file to LF so a Windows checkout and a WSL
test run see the same bytes.
