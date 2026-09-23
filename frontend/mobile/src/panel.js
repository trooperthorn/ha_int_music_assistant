import { LitElement, css, html, nothing } from "lit";

const VIEWS = new Set(["library", "routing", "settings"]);
const STORAGE_KEY = "ma-mobile-selected-player";
const PAGE_SIZE = 30;
const CATEGORIES = ["artist", "album", "track", "playlist", "radio", "podcast", "audiobook"];

class MusicAssistantMobilePanel extends LitElement {
  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    route: { attribute: false },
    panel: { attribute: false },
    _view: { state: true },
    _selectedId: { state: true },
    _busy: { state: true },
    _error: { state: true },
    _entryId: { state: true },
    _category: { state: true },
    _items: { state: true },
    _loading: { state: true },
    _hasMore: { state: true },
    _query: { state: true },
  };

  constructor() {
    super();
    this._view = this._readView();
    this._selectedId = sessionStorage.getItem(STORAGE_KEY) || "";
    this._busy = false;
    this._error = "";
    this._entryId = "";
    this._category = "artist";
    this._items = [];
    this._loading = false;
    this._hasMore = true;
    this._query = "";
    this._requestId = 0;
    this._searchTimer = undefined;
    this._onHashChange = () => {
      this._view = this._readView();
    };
    this._onSelectedPlayer = (event) => {
      this._selectedId = event.detail;
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hashchange", this._onHashChange);
    window.addEventListener("ma-mobile-player-selected", this._onSelectedPlayer);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHashChange);
    window.removeEventListener("ma-mobile-player-selected", this._onSelectedPlayer);
    clearTimeout(this._searchTimer);
    super.disconnectedCallback();
  }

  updated(changed) {
    if (changed.has("hass") && this.hass?.callWS && !this._entryId) {
      this._loadEntry();
    }
  }

  async _loadEntry() {
    if (this._entryLoading) return;
    this._entryLoading = true;
    try {
      const entries = await this.hass.callWS({
        type: "config_entries/get",
        domain: "music_assistant",
      });
      const entry = entries.find((item) => item.state === "loaded") || entries[0];
      if (entry) {
        this._entryId = entry.entry_id;
        await this._loadLibrary(true);
      } else {
        this._error = "Configure Music Assistant to browse the library.";
      }
    } catch (error) {
      this._error = error?.message || "The Music Assistant connection could not be found.";
    } finally {
      this._entryLoading = false;
    }
  }

  async _loadLibrary(reset = false) {
    if (!this._entryId || (this._loading && !reset)) return;
    const requestId = ++this._requestId;
    const offset = reset ? 0 : this._items.length;
    if (reset) {
      this._items = [];
      this._hasMore = true;
    }
    this._loading = true;
    this._error = "";
    try {
      const result = await this.hass.callService(
        "music_assistant",
        "get_library",
        {
          config_entry_id: this._entryId,
          media_type: this._category,
          limit: PAGE_SIZE,
          offset,
          ...(this._query ? { search: this._query } : {}),
        },
        undefined,
        false,
        true,
      );
      if (requestId !== this._requestId) return;
      const items = result.response?.items || [];
      this._items = reset ? items : [...this._items, ...items];
      this._hasMore = items.length === PAGE_SIZE;
    } catch (error) {
      if (requestId === this._requestId) {
        this._error = error?.message || "The library could not be loaded.";
      }
    } finally {
      if (requestId === this._requestId) this._loading = false;
    }
  }

  _setCategory(category) {
    if (category === this._category) return;
    this._category = category;
    this._loadLibrary(true);
  }

  _onSearch(event) {
    this._query = event.target.value.trim();
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => this._loadLibrary(true), 300);
  }

  async _playItem(item) {
    this._error = "";
    window.dispatchEvent(new CustomEvent("ma-mobile-play-local", { detail: item }));
  }

  _readView() {
    const view = window.location.hash.replace(/^#\/?/, "").split("/")[0];
    return VIEWS.has(view) ? view : "library";
  }

  _showView(view) {
    if (!VIEWS.has(view) || this._view === view) return;
    window.location.hash = view;
    this._view = view;
  }

  get _players() {
    if (!this.hass?.states) return [];
    return Object.values(this.hass.states)
      .filter(
        (state) =>
          state.entity_id.startsWith("media_player.") &&
          typeof state.attributes?.mass_player_type === "string",
      )
      .sort((a, b) =>
        this._name(a).localeCompare(this._name(b), this.hass.language || undefined),
      );
  }

  _name(state) {
    return state.attributes.friendly_name || state.entity_id;
  }

  get _selectedPlayer() {
    const players = this._players;
    return (
      players.find((player) => player.entity_id === this._selectedId) ||
      players[0]
    );
  }

  _selectPlayer(entityId) {
    this._selectedId = entityId;
    sessionStorage.setItem(STORAGE_KEY, entityId);
    window.dispatchEvent(new CustomEvent("ma-mobile-player-selected", { detail: entityId }));
    this._error = "";
  }

  async _control(action) {
    const player = this._selectedPlayer;
    if (!player || this._busy) return;
    this._busy = true;
    this._error = "";
    try {
      await this.hass.callService("media_player", action, {
        entity_id: player.entity_id,
      });
    } catch (error) {
      this._error = error?.message || "The player could not be controlled.";
    } finally {
      this._busy = false;
    }
  }

  _renderPlayer() {
    const player = this._selectedPlayer;
    if (!player) {
      return html`<div class="player empty" role="status">
        No Music Assistant players are exposed to Home Assistant yet.
      </div>`;
    }
    const title = player.attributes.media_title || "Nothing playing";
    const artist = player.attributes.media_artist || this._name(player);
    const isPlaying = player.state === "playing";
    const canControl = player.state !== "unavailable" && player.state !== "unknown";
    return html`<div class="player" aria-label="Selected player">
      <div class="player-copy">
        <div class="player-title">${title}</div>
        <div class="secondary">${artist} · ${this._name(player)}</div>
      </div>
      <div class="player-actions">
        <button
          type="button"
          aria-label="Previous track"
          ?disabled=${!canControl || this._busy}
          @click=${() => this._control("media_previous_track")}
        ><ha-icon icon="mdi:skip-previous"></ha-icon></button>
        <button
          type="button"
          class="primary"
          aria-label=${isPlaying ? "Pause" : "Play"}
          ?disabled=${!canControl || this._busy}
          @click=${() => this._control(isPlaying ? "media_pause" : "media_play")}
        ><ha-icon icon=${isPlaying ? "mdi:pause" : "mdi:play"}></ha-icon></button>
        <button
          type="button"
          aria-label="Next track"
          ?disabled=${!canControl || this._busy}
          @click=${() => this._control("media_next_track")}
        ><ha-icon icon="mdi:skip-next"></ha-icon></button>
      </div>
    </div>`;
  }

  _renderLibrary() {
    return html`<section aria-labelledby="library-title">
      <h2 id="library-title">Music Library</h2>
      <div class="library-tools">
        <label class="search-label">Search library
          <input type="search" placeholder="Search ${this._category}s" .value=${this._query} @input=${this._onSearch}>
        </label>
        <span class="secondary">Output: This browser</span>
      </div>
      <div class="categories" role="group" aria-label="Library category">
        ${CATEGORIES.map((category) => html`<button type="button"
          class=${this._category === category ? "active" : ""}
          aria-pressed=${this._category === category}
          @click=${() => this._setCategory(category)}>${category[0].toUpperCase() + category.slice(1)}s</button>`)}
      </div>
      ${this._items.length ? html`<div class="library-list">
        ${this._items.map((item) => html`<button type="button" class="library-row"
          aria-label=${`Play ${item.name} in this browser`}
          @click=${() => this._playItem(item)}>
          ${item.image ? html`<img src=${item.image} alt="" loading="lazy" referrerpolicy="no-referrer">` : html`<span class="art-placeholder"><ha-icon icon="mdi:music"></ha-icon></span>`}
          <span class="library-copy"><strong>${item.name}</strong><small>${item.artists?.map((artist) => artist.name).join(", ") || item.album?.name || item.media_type}</small></span>
          <ha-icon icon="mdi:play" aria-hidden="true"></ha-icon>
        </button>`)}
      </div>` : !this._loading ? html`<p role="status">${this._entryId ? "No library items found." : "Connecting to Music Assistant…"}</p>` : nothing}
      ${this._loading ? html`<p role="status">Loading library…</p>` : nothing}
      ${this._hasMore && !this._loading && this._entryId ? html`<button class="more-button" type="button" @click=${() => this._loadLibrary()}>Load more</button>` : nothing}
    </section>`;
  }

  _renderRouting() {
    return html`<section aria-labelledby="routing-title">
      <h2 id="routing-title">Music Routing</h2>
      <p class="secondary">This test build plays locally in the current browser only.</p>
      <div class="route-row selected" aria-current="true"><ha-icon icon="mdi:cellphone-sound"></ha-icon><span class="route-copy"><strong>This browser</strong><small>Local Sendspin audio</small></span><ha-icon icon="mdi:check-circle" aria-hidden="true"></ha-icon></div>
    </section>`;
  }

  _renderSettings() {
    return html`<section aria-labelledby="settings-title">
      <h2 id="settings-title">Music Settings</h2>
      <div class="setting-row">
        <span>Selected output</span>
        <strong>This browser</strong>
      </div>
      <p class="secondary">
        Player and server settings already exposed by Home Assistant remain in
        their native entity controls. Additional settings will be added only
        when their Music Assistant capability is verified.
      </p>
    </section>`;
  }

  render() {
    return html`<div class="page">
      <header>
        <p class="eyebrow">Music Assistant</p>
        <h1>Music</h1>
      </header>
      <nav aria-label="Music sections">
        ${["library", "routing", "settings"].map(
          (view) => html`<button
            type="button"
            class=${this._view === view ? "active" : ""}
            aria-current=${this._view === view ? "page" : nothing}
            @click=${() => this._showView(view)}
          >${view[0].toUpperCase() + view.slice(1)}</button>`,
        )}
      </nav>
      ${this._view === "library"
        ? this._renderLibrary()
        : this._view === "routing"
          ? this._renderRouting()
          : this._renderSettings()}
      ${this._error
        ? html`<p class="error" role="alert">${this._error}</p>`
        : nothing}
    </div>`;
  }

  static styles = css`
    :host{display:block;min-height:100%;color:var(--primary-text-color);background:var(--primary-background-color);font-family:var(--ha-font-family-body,Roboto,"Segoe UI",sans-serif)}
    *{box-sizing:border-box}.page{max-width:1100px;margin:0 auto;padding:20px 18px 130px}header{padding:8px 0 14px}.eyebrow{color:var(--primary-color);font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin:0 0 6px}h1{font-size:30px;line-height:1.2;margin:0}h2{font-size:22px;margin:0 0 10px}nav{display:flex;gap:8px;overflow-x:auto;padding:4px 0 20px}button{cursor:pointer;font:inherit}nav button{border:1px solid var(--divider-color);border-radius:999px;background:var(--card-background-color);color:var(--primary-text-color);padding:10px 17px;min-height:44px;white-space:nowrap}nav button.active{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}button:focus-visible{outline:3px solid var(--primary-color);outline-offset:3px}section{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:16px;padding:20px;min-height:200px}.secondary{color:var(--secondary-text-color);line-height:1.5}.link-button{display:flex;align-items:center;gap:6px;border:0;background:transparent;color:var(--primary-color);padding:12px 0;min-height:44px}.route-list{display:grid;gap:8px;margin-top:18px}.route-row{display:flex;align-items:center;gap:12px;width:100%;padding:12px;border:1px solid var(--divider-color);border-radius:12px;background:var(--secondary-background-color);color:var(--primary-text-color);text-align:left;min-height:64px}.route-row.selected{border-color:var(--primary-color)}.route-copy{display:flex;flex-direction:column;gap:3px;flex:1}.route-copy small{color:var(--secondary-text-color)}.setting-row{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--divider-color);padding:16px 0}.player{position:fixed;bottom:var(--safe-area-inset-bottom,0px);left:var(--ha-sidebar-width,0px);right:0;min-height:78px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 22px;background:var(--card-background-color);border-top:1px solid var(--divider-color);box-shadow:0 -3px 16px #0002}.player.empty{color:var(--secondary-text-color)}.player-copy{min-width:0}.player-title{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.player-actions{display:flex;gap:8px}.player-actions button{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:50%;background:var(--secondary-background-color);color:var(--primary-text-color)}.player-actions button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff)}.player-actions button:disabled{opacity:.5;cursor:not-allowed}.error{color:var(--error-color);padding:12px}ha-icon{--mdc-icon-size:22px}.library-tools{display:flex;align-items:end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:18px 0}.search-label{display:grid;gap:6px;font-weight:600;min-width:min(100%,320px)}input{font:inherit;min-height:44px;border:1px solid var(--divider-color);border-radius:10px;padding:8px 12px;background:var(--secondary-background-color);color:var(--primary-text-color)}.categories{display:flex;gap:6px;overflow-x:auto;padding:4px 0 16px}.categories button{min-height:40px;padding:7px 13px;border-radius:10px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color)}.categories button.active{border-color:var(--primary-color);color:var(--primary-color)}.library-list{display:grid;gap:4px}.library-row{width:100%;display:flex;align-items:center;gap:12px;min-height:64px;padding:7px;border:0;border-bottom:1px solid var(--divider-color);background:transparent;color:var(--primary-text-color);text-align:left}.library-row img,.art-placeholder{width:50px;height:50px;flex:none;object-fit:cover;border-radius:6px;background:var(--secondary-background-color)}.art-placeholder{display:grid;place-items:center}.library-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px}.library-copy strong,.library-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.library-copy small{color:var(--secondary-text-color)}.more-button{min-height:44px;margin:16px 0 0;border:1px solid var(--divider-color);border-radius:10px;padding:8px 18px;background:var(--secondary-background-color);color:var(--primary-text-color)}
    @media(max-width:760px){.page{padding:14px 14px 112px}h1{font-size:27px}section{padding:16px}.player{left:0;min-height:68px;padding:8px 12px}.player .secondary{font-size:12px}.player-actions{gap:2px}.player-actions button{width:40px;height:40px}}
  `;
}

if (!customElements.get("ma-mobile-panel")) {
  customElements.define("ma-mobile-panel", MusicAssistantMobilePanel);
}

