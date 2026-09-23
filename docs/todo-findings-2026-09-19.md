# Handoff: Music Assistant TODO triage — upstream + fork findings

**Date:** 2026-09-19
**Source TODO:** `C:\Users\sean.LAB\Downloads\TODO.md` (cross-repo UI/backend follow-ups)

**Repos examined:**
- Upstream: `music-assistant/server` (issues + PRs, all states) and `music-assistant/support`
- Fork: `trooperthorn/HA_int_MA-UI`, local clone `~/repos/HA_int_MA-UI`, pulled to `3937af44` ("Fix eight library-manager and player UI workflow issues", PR #54)
- Packager: `~/repos/ha_app_music_assistant`

**Nothing was filed, opened, or changed upstream.** No code was modified in either repo. This is research output only.

---

## TL;DR for the executing agent

| TODO item | Verdict | Work remaining |
|---|---|---|
| 1. Artist "All" view shows no songs | **Not a server bug.** Documented upstream behavior since 2026-06. Fork still calls the wrong endpoint. | **Yes — the only real code fix.** ~5 lines in `useItemSource.ts`. |
| 2a. "Replace Up Next" merged control | Already shipped and documented in code | None |
| 2b. Fullscreen player load-minimized | Already shipped | None (open "blue bar" question needs a screenshot from Sean) |
| 3a. Spotify playlist import | Mostly shipped, via M3U import + playlist migrate | **Verify a dependency risk — see §4** |
| 3b. Equalizer / DSP | Fully shipped upstream *and* in the fork | None |
| 3b'. Streaming quality/delay | Partially shipped (`audio_delay` only) | Optional |

**Priority order:** §4 (runtime-breaking risk) > §1 (the actual bug) > everything else.

---

## 1. Artist "All" view shows no songs — THE FIX

### Root cause, confirmed against real source

Upstream PR [music-assistant/server#4039](https://github.com/music-assistant/server/pull/4039)
*"Separate library artist views from per-provider artist listings"* — **merged 2026-06-08** —
deliberately redefined the RPC the fork calls.

Read from `music_assistant/controllers/music/media/artists.py` on `dev`:

- `music/artists/artist_tracks` with `provider == "library"` dispatches to
  `get_library_artist_tracks()`, which returns **only tracks already in the library**,
  joined via the `track_artists` table with `in_library_only=True`. It does **not**
  fall back to the provider catalog.
- `music/artists/top_tracks` is the endpoint that aggregates across all of the artist's
  providers, deduplicates, and resolves to library equivalents.
- The album path behaves differently on purpose: `get_provider_artist_tracks()` *does*
  fall back to enumerating the provider's albums when `ARTIST_TRACKS` is unsupported.

So "Goo Goo Dolls" showing zero tracks while its albums show tracks is the **expected**
result when the albums are in the library but the individual tracks are not.
This is a frontend call-site problem, not a server bug.

Two additional silent-empty guards exist in that file, worth knowing when debugging:

- `if library_item.artist_type != ArtistType.SINGER: return []` — logged at debug only.
  (`ArtistType` is SINGER / AUTHOR / NARRATOR — music vs. audiobook. A band is SINGER,
  so this should not normally fire, but an audiobook-provider misclassification would.)
- An unavailable or missing provider returns `[]` with no error.

### Where the fork is wrong

File: `src/library-manager/composables/useItemSource.ts`, around **line 241-255**.

```ts
    if (current.mediaType === MediaType.TRACK && current.album) {
      return api
        .getAlbumTracks(current.album.item_id, current.album.provider)
        .then((items) => sortBrowseTracksLocally(current, items));
    }
    if (current.mediaType === MediaType.TRACK && current.artist) {
      return api
        .getArtistTracks(current.artist.item_id, current.artist.provider)   // <-- library-only
        .then((items) => sortBrowseTracksLocally(current, items));
    }
```

`api.getArtistTracks` is defined at `src/plugins/api/index.ts:691` and sends
`music/artists/artist_tracks`. `api.getArtistTopTracks` at `src/plugins/api/index.ts:703`
sends `music/artists/top_tracks`. Both already accept an optional `provider_filter`
third argument.

### The fork already solved this correctly elsewhere — copy that pattern

`src/components/artist/artistData.ts` models both paths properly for the artist
detail page and even documents the distinction in its doc comments:

- `loadArtistLibraryTracks(artist, providerFilter?)` — commented
  *"The artist's in-library tracks, optionally limited to a single provider."*
- `loadArtistTopTracks(artist, source)` — commented
  *"The artist's most popular tracks, as reported by `source`."* Uses
  `aggregatedProviderFilter(artist, source)`.
- `loadArtistReleases(artist, source)` — handles the library-vs-provider-mapping split.

`src/views/ArtistDetails.vue` even labels the row with `n_in_library` (line ~242),
i.e. the detail page tells the user these are library-only counts.
The **Library Manager browse scope never got that treatment.**

### Suggested fix (two options — pick one, do not do both)

**Option A (minimal, recommended):** fall back when the library result is empty.

```ts
    if (current.mediaType === MediaType.TRACK && current.artist) {
      const { item_id, provider } = current.artist;
      return api
        .getArtistTracks(item_id, provider)
        .then((items) =>
          items.length ? items : api.getArtistTopTracks(item_id, provider),
        )
        .then((items) => sortBrowseTracksLocally(current, items));
    }
```

**Option B (more complete, more work):** aggregate `getArtistAlbums` →
`getAlbumTracks` client-side and dedupe, mirroring the server's own
`get_provider_artist_tracks` fallback. Heavier: N+1 round trips per artist.

Note the original TODO explicitly said *"do not attempt a frontend workaround
... without confirming this is really a server bug."* That confirmation is now done:
**it is not a server bug**, so a frontend change is the correct and only fix.
The TODO's "Sean to file an upstream issue" action can be dropped.

### Related upstream work worth knowing (context, not blockers)

- [server#6324](https://github.com/music-assistant/server/pull/6324) *"Keep same-provider artists with different ids apart"* — **OPEN**, held in draft by an automated critical-issue gate. This is the multi-provider identity-merge hypothesis from the TODO; a maintainer confirmed the underlying problem is real (e.g. Tidal "loud" vs "LOUD").
- [server#6327](https://github.com/music-assistant/server/pull/6327) repair pass to split already-merged library artists — **closed unmerged.** jozefKruszynski: an automated split is unsafe, because Tidal legitimately lists one artist under two ids with an identical name (GUNSHIP, Seeb). Existing libraries stay merged.
- [server#6362](https://github.com/music-assistant/server/pull/6362) — **merged 2026-09-15** — fixed library artists/albums picking up a bogus provider link (provider literally the string `"None"`) that made the item page query a non-existent provider for extras. Mostly Qobuz artists; symptom is `"User does not have permission to access the requested provider(s)"` in the log. **If the deployed server predates this, upgrade before doing any further artist debugging.**
- Also merged: [#5845](https://github.com/music-assistant/server/pull/5845) / [#5846](https://github.com/music-assistant/server/pull/5846) (repair tracks missing their artist), [#5405](https://github.com/music-assistant/server/pull/5405) (Plex artist top tracks always empty).
- [server#6279](https://github.com/music-assistant/server/pull/6279) added a `music/artists/discography` command — **closed unmerged.** marcelveldt: a real discography should come from a metadata source like MusicBrainz; merging provider catalogs reintroduces the confusion the old artist-albums listing had. **Do not build against `music/artists/discography` — it does not exist.**

---

## 2. Product decisions from the TODO — both already shipped

### 2a. "Replace Up Next" vs "Use as Up Next"

Addressed and documented **in code**, so the decision is durable:

`src/library-manager/LibraryManagerView.vue:741` carries an explicit comment recording
that the two originally-separate asks were merged because they described the same
behavior. `replaceUpNext()` is at line 746; the button is at lines 253-257.
Translation strings: `library_manager.replace_up_next` and
`library_manager.replace_up_next_hint` ("Clear up next and queue these tracks, in the
order shown") in `src/translations/en.json:2871-2872`.

**No action.** If a genuinely distinct second behavior was intended, that is a new
product ask, not a regression.

### 2b. Fullscreen player auto-opening ("blue bar on the left")

Addressed. `src/layouts/default/Default.vue:44-80` handles the stale
`?showFullscreenPlayer=1` query param, with a comment at line 44 noting that a
restored/bookmarked/shared URL can carry one, and logic at line 56 that skips honoring
it on first mount.

**Still open (non-code):** nothing left-docked exists in the tree — a grep for a
left-docked bar finds nothing, and the only persistent player bar is full-width at the
bottom. If Sean meant a different component, that needs a screenshot. Do not guess.

---

## 3. Equalizer and streaming quality — done, do not build

### Equalizer / DSP: fully shipped upstream AND present in the fork

Upstream history:

- [server#1795](https://github.com/music-assistant/server/pull/1795) Configurable DSP with **Parametric Equalizer** — merged 2024-12-20 (replaced the old EQ, with automatic migration)
- [server#2031](https://github.com/music-assistant/server/pull/2031) **multichannel** PEQ — merged 2025-03-13
- July 2026 filter family, all merged: gain/balance [#4857](https://github.com/music-assistant/server/pull/4857), high/low-pass [#4944](https://github.com/music-assistant/server/pull/4944), convolution [#4947](https://github.com/music-assistant/server/pull/4947), stereo width + crossfeed [#4971](https://github.com/music-assistant/server/pull/4971), limiter + compressor [#5004](https://github.com/music-assistant/server/pull/5004), transpose [#5005](https://github.com/music-assistant/server/pull/5005); plus [#6104](https://github.com/music-assistant/server/pull/6104) (balance on mono tracks)

Present in `~/repos/HA_int_MA-UI`:

```
src/components/dsp/DSPParametricEQ.vue      src/components/dsp/DSPPipeline.vue
src/components/dsp/DSPCompressor.vue        src/components/dsp/DSPConvolution.vue
src/components/dsp/DSPCrossfeed.vue         src/components/dsp/DSPHighLowPass.vue
src/components/dsp/DSPSafetyLimiter.vue     src/components/dsp/DSPStereoWidth.vue
src/components/dsp/DSPToneControl.vue       src/components/dsp/DSPTranspose.vue
src/components/dsp/DSPIRManager.vue         src/components/dsp/DSPSlider.vue
src/components/dsp/highLowPass.ts           src/views/settings/EditPlayerDsp.vue
src/composables/useDSPIRs.ts                src/composables/useAudioProcessingDetails.ts
src/assets/dsp.svg                          src/assets/dsp-disabled.svg
```

**No action. Delete this item from the TODO — it was already done before the TODO was written.**

### Streaming quality / delay: partially shipped

- Fork has `audio_delay` as a player menu item (`src/helpers/player_menu_items.ts:428`),
  registered as a preference in `src/helpers/player_menu_preferences.ts:29`,
  string at `src/translations/en.json:424`.
- Upstream has **no general** streaming-quality setting.
  [server#5882](https://github.com/music-assistant/server/pull/5882) (merged) added one,
  but it is **Spotify-Connect-specific only**.
- Nearest other work: flow-stream buffering/crossfade fixes
  [#3645](https://github.com/music-assistant/server/pull/3645),
  [#6132](https://github.com/music-assistant/server/pull/6132).

**Optional.** Scope separately if wanted; there is no upstream API to wrap.

---

## 4. ACTION REQUIRED — `migrate_playlist` depends on an unmerged upstream PR

This is a **new finding**, not in the original TODO, and it is the highest-risk item.

The fork ships `src/layouts/default/MigratePlaylistDialog.vue`, reachable from
`src/layouts/default/ItemContextMenu.vue:1093` (`migrate_playlist.action`), calling:

```ts
// src/plugins/api/index.ts:987
public migratePlaylist(
  db_playlist_id: string | number,
  destination_provider: string,
  match_policy: PlaylistMatchPolicy,
  name?: string,
): Promise<BackgroundTask> {
  return this.sendCommand<BackgroundTask>("music/playlists/migrate_playlist", { ... });
}
```

`music/playlists/migrate_playlist` comes from upstream
[server#5926](https://github.com/music-assistant/server/pull/5926)
*"Migrate playlists between providers"* — which is **CLOSED, UNMERGED.**
The command does not exist in upstream `dev`.

I found **no patch files and no `migrate_playlist` reference** anywhere in
`~/repos/ha_app_music_assistant` (checked `scripts/`, `docs/`, all `.py` and `.md`).
That repo has `scripts/sync_upstream.py`, `docs/upstream-review.md` and
`docs/upstream-review-notes.md` but no evidence of carrying this command.

### What to do

1. Confirm against the running server whether `music/playlists/migrate_playlist` is
   registered. If it is not, the Migrate Playlist dialog fails at runtime for the user.
2. Then pick one:
   - **Carry the patch** in `ha_app_music_assistant` (port #5926's server side into the
     bundled server, and record it in `docs/upstream-review.md`), or
   - **Feature-gate the UI** — hide the context-menu entry unless the command is present,
     e.g. via the API schema version / command catalog, or
   - **Remove the dialog** and rely on the M3U export/import path below.

---

## 5. Spotify playlist import — mostly shipped, via a different route than the TODO assumed

Upstream [server#3387](https://github.com/music-assistant/server/pull/3387)
*"Create Services for Playlist Export / Import"* — **merged 2026-03-30** — added:

- `music/playlists/export_playlist(db_playlist_id)` → M3U8 string with extended tags
- `music/playlists/import_playlist(m3u_data, library_matching, match_providers, match_policy)`
  with background **library matching**: tiered strategy, exact ID match on
  **ISRC/MusicBrainz** first, then fuzzy metadata fallback, optionally restricted to
  named providers.

Also merged: [server#5986](https://github.com/music-assistant/server/pull/5986) —
re-matches imported playlist tracks against other providers when the original source
is gone.

The fork already exposes all of this:

- `src/layouts/default/ImportPlaylistDialog.vue` — provider selection plus
  exact / same-recording / best-effort match policies; triggered from
  `src/views/LibraryPlaylists.vue:219` via the `importPlaylistDialog` eventbus event
  (`src/plugins/eventbus.ts:121`)
- `api.importPlaylist` at `src/plugins/api/index.ts:973`,
  `api.exportPlaylist` at `src/plugins/api/index.ts:967`
- Export as `.m3u8` download from `src/layouts/default/ItemContextMenu.vue:1062-1074`

**Gap that genuinely remains:** importing a Spotify playlist into a **local playlist
file on the filesystem**. Upstream's matching is ISRC/MusicBrainz-tiered, but the
import destination is a *builtin* playlist, not a filesystem `.m3u`. If that specific
destination matters, it is a new scoping item — but it is much smaller than the TODO
implied, since the matching engine already exists server-side.

**Recommended rescope:** change this TODO item from "implement Spotify playlist import
with MusicBrainz matching" to "decide whether builtin-playlist destination is
sufficient; if not, add a filesystem write step."

---

## 6. Notes on the upstream repo, if anyone does contribute later

- `music-assistant/server` has **almost no user-filed issues** — user reports go to
  `music-assistant/support`. Search both.
- **No `wontfix` or `not planned` labels are in use** anywhere in the repo, so "marked
  will not fix" shows up only as a closed-unmerged PR with a maintainer comment
  (as with #6279, #6327, #5926).
- There is an **automated critical-issue gate** that forces PRs into draft until
  `[CRITICAL]` automated-review threads are resolved. Maintainers bypass it with an
  `override-critical` label.
- `.github/workflows/pr-labels.yaml` derives the release-note label from the single
  ticked checkbox in the PR body template. The body format matters.
- **Standing constraint:** no PRs or issues are to be opened on non-`trooperthorn`
  repos. Gaps get documented as follow-ups instead. Nothing was filed upstream here.

---

## 7. Suggested execution order

1. **Verify** `music/playlists/migrate_playlist` exists on the deployed server (§4).
   Decide patch / gate / remove.
2. **Verify** the deployed server includes [#6362](https://github.com/music-assistant/server/pull/6362)
   (merged 2026-09-15) before any artist debugging (§1).
3. **Fix** `useItemSource.ts` per §1 Option A. Single call site.
4. **Rewrite** `TODO.md`: drop item 1's upstream-report action, drop item 3b (equalizer)
   entirely, rescope item 3a per §5, and add §4 as a new tracked item.
5. Leave item 2 alone except the open "blue bar" question, which needs a screenshot.
