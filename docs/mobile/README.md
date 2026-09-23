# Mobile branch: native Music Assistant design and phased work

Status: initial test framework with Library browsing and an app-wide player bubble is built on this isolated branch. Installing the `Mobile` branch adds a Music sidebar page. The separate `prototype.html` remains a static visual mock.

## Objective

Give Music Assistant a responsive Home Assistant page for Library, Routing, and selected Settings, with a compact music control in the Home Assistant top bar. On mobile, the control sits immediately left of the **+** action shown in the owner's screenshot. The control opens a compact player below the bar. Navigation among Home Assistant pages should leave local playback running when the browser document remains alive.

The branch name is `Mobile`. Do not merge it into `main`, publish a release, or deploy it to the owner's Home Assistant instance without the owner's explicit approval of a concrete implementation and live test plan.

## Starting point

- Base: `main` commit `fa22099ab5c6b41450a5310ccbdb08c3a498b8dd`.
- Integration: `custom_components/music_assistant`, Home Assistant 2026.9.0, Python 3.14, `music-assistant-client==1.5.1`.
- Existing integration already has push-driven player and queue state, Library browsing/search, `get_library`, `get_queue`, `play_media`, and `transfer_queue`. Its `media_browser.py` documents the limits of the generic HA Media Browser for a rich Library view.
- The existing fork keeps the `music_assistant` domain and is designed to override Home Assistant's built-in integration without changing entity identity. Preserve that contract.
- Branch content now: this design, a standalone visual prototype, a bundled Lit panel, and panel registration in the integration. `main` and all releases remain unchanged.

## Core distinction

Home Assistant's Media Browser can resolve a `media-source://` item and play audio in the current browser, including the Companion app WebView. Its current `ha-bar-media-player` is owned by the Media Browser panel and calls player teardown when disconnected. Therefore, page navigation can stop that local audio. A visible button alone does not change this; the audio engine must outlive the page.

Sources: [Media Source](https://www.home-assistant.io/integrations/media_source/), [Media Browser selection](https://github.com/home-assistant/frontend/blob/dev/src/panels/media-browser/ha-panel-media-browser.ts), [player teardown](https://github.com/home-assistant/frontend/blob/dev/src/panels/media-browser/ha-bar-media-player.ts), [HTML audio player](https://github.com/home-assistant/frontend/blob/dev/src/panels/media-browser/browser-media-player.ts).

## Experience contract

1. The Music page follows Home Assistant theme, typography, focus indication, minimum touch target size, and screen-reader naming.
2. Library supports source/category browsing, search, recent items, paged results, and a clear selected playback target. It does not block initial render on all library counts.
3. Routing lists browser and remote outputs with availability and selected state. Settings contains only controls backed by verified integration capabilities.
4. On mobile, the music button is in the persistent HA top bar, immediately left of **+**, with a clear active state. On desktop, it remains in the top bar.
5. The compact player shows artwork, title, artist, output, play/pause, previous/next when available, progress, Queue, and Change output. Collapsing it hides controls but does not issue Stop.
6. Back moves through Music subpages before leaving Music. Leaving Music or opening another HA page must not issue Stop to a remote player. Local browser audio continuity is a separate acceptance test.
7. Full reload, browser tab close, Companion app process death, screen lock, and app backgrounding are recorded as distinct behaviors. Do not claim they are solved by same-document navigation.

## Phases and gates

| Phase | Branch-only deliverable | Exit test |
| --- | --- | --- |
| 0. Inventory | Current integration/API/frontend versions, exact player mode, navigation trace, timing baseline, and code ownership map. | The team can reproduce the stop and distinguish local browser from remote player. |
| 1. Visual design | Responsive static prototype in [prototype.html](prototype.html), design review, mobile and desktop states. | Owner approves placement, navigation, labels, and accessibility layout before connecting data. |
| 2. Native page shell | Built: bundled Lit custom panel served by the integration; HA theme, `hass`, Library/Routing/Settings routes, no direct browser-to-MA credentials. | Static build passes; live page mounting and Chrome/Android navigation await an isolated HA test instance. |
| 3. Data and actions | Built for initial testing: Library category browsing, 30-item pages, search, cover art, and play action through existing Home Assistant services. Details and queue views remain future work. | The existing `get_library` response action is bounded; real large-library performance and item playback await live testing. |
| 4. Persistent player feasibility | Built for initial testing: app-wide Lit bubble loaded through Home Assistant's extra-module hook. It controls exposed remote Music Assistant players and sits left of header actions when their layout is found. | Chrome and Android page navigation, header placement, and lifecycle still need live testing. Local browser audio playback is not implemented. |
| 5. Mobile acceptance | Device matrix, keyboard/screen reader, orientation, safe areas, screen lock/background, stream URL reachability, codec support, queue transition, reconnection. | Results state precisely which transitions pass, fail, or are unsupported. |
| 6. Release decision | Owner reviews measured performance, UX, compatibility, and rollback evidence. | Merge/deploy/release only after explicit owner approval. |

## Implementation boundaries

- Keep Python integration responsibilities in this repository. Do not change the Music Assistant server or the current MA web app until a specific missing API is demonstrated.
- The Lit page is a normal custom panel. The global bubble is a separate app-wide module registered through Home Assistant's `frontend.add_extra_js_url`; it mounts outside the panel lifecycle. Its position uses current header internals and may need adjustment after HA frontend upgrades.
- A top-bar extension may rely on private HA frontend structure. Before adopting it, record which supported API exists, what may break on HA upgrades, and whether a less intrusive Browser Mod style plugin is preferable.
- Do not use an ingress iframe as the persistent audio host.
- No external CDN, new runtime library, credential storage in browser JavaScript, or direct MA socket from the page.
- Preserve current integration entities, actions, config entries, and release behavior.

## Verification ledger

- Confirmed from source: current HA Media Browser's player is panel-owned and explicitly paused on teardown.
- Confirmed from owner's browser: current MA Library uses compact artwork rows and a dark mobile layout; the desired HA bar has **+**, search, conversation, and overflow actions.
- Built on `Mobile`: the Music sidebar page, selected exposed Music Assistant player, HA service calls for play/pause/previous/next, paged Library browsing/search, and an app-wide remote-player bubble. The source is in `frontend/mobile/src/panel.js`; the self-contained build output is `custom_components/music_assistant/mobile/panel.js`.
- The live bubble is registered in HA and remains mounted across same-document navigation. It controls remote Music Assistant players. It is not yet a browser-audio engine, so local phone/browser playback continuity is unproven.
- Library uses the existing bounded `get_library` action rather than a second backend connection. Routing and the bubble list only players exposed as Home Assistant media player entities. Expanded settings, queue, item details, and browser-audio playback remain future work.
- Untested: actual top-bar injection, local playback through page navigation, Android background audio, Media Source support for MA provider URLs, and production performance.

## Rollback

The experiment is contained in `Mobile`. Until a reviewed merge, `main` and its releases stay at their current behavior. If the persistent header/player is not maintainable, leave this branch unmerged and retain the findings as an architectural record.

## Building the panel

From `frontend/mobile`, run `npm ci` and `npm run build`. The build bundles Lit locally into `custom_components/music_assistant/mobile/panel.js` and `bubble.js`; Home Assistant serves that file from its own origin. No CDN is used. The installed integration does not need Node.js or npm.

The branch is intended for a separate test Home Assistant instance. Installing it replaces the normal `music_assistant` integration code for that instance and adds a Music sidebar entry; it does not install into the owner's running instance automatically.

## Initial live test

Use a disposable Home Assistant test instance with the `Mobile` branch. Confirm the Music sidebar page loads, Library categories return real items in 30-item pages, search narrows results, and selecting a track plays on an exposed Music Assistant player. Visit several HA pages with Back and sidebar navigation and confirm the bubble stays present, remains left of the header actions, and can control that remote player. Record Android Companion behavior separately from Chrome. Local browser audio, app backgrounding, process death, and screen lock are still distinct untested cases.
