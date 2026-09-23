import { LitElement, css, html, nothing } from "lit";

const VIEWS = new Set(["library", "routing", "settings"]);
const STORAGE_KEY = "ma-mobile-selected-player";

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
  };

  constructor() {
    super();
    this._view = this._readView();
    this._selectedId = sessionStorage.getItem(STORAGE_KEY) || "";
    this._busy = false;
    this._error = "";
    this._onHashChange = () => {
      this._view = this._readView();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hashchange", this._onHashChange);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHashChange);
    super.disconnectedCallback();
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
      <p class="secondary">
        Your library will appear here when the paged Music Assistant data API
        is connected. The page and player selection are ready for that step.
      </p>
      <button class="link-button" type="button" @click=${() => this._showView("routing")}>
        Choose a player <ha-icon icon="mdi:arrow-right"></ha-icon>
      </button>
    </section>`;
  }

  _renderRouting() {
    const players = this._players;
    return html`<section aria-labelledby="routing-title">
      <h2 id="routing-title">Music Routing</h2>
      <p class="secondary">Select the Music Assistant player to control.</p>
      ${players.length
        ? html`<div class="route-list">
            ${players.map(
              (player) => html`<button
                class="route-row ${this._selectedPlayer?.entity_id === player.entity_id
                  ? "selected"
                  : ""}"
                type="button"
                aria-pressed=${this._selectedPlayer?.entity_id === player.entity_id}
                @click=${() => this._selectPlayer(player.entity_id)}
              >
                <ha-icon icon="mdi:speaker"></ha-icon>
                <span class="route-copy"><strong>${this._name(player)}</strong>
                  <small>${player.state}</small></span>
                ${this._selectedPlayer?.entity_id === player.entity_id
                  ? html`<ha-icon icon="mdi:check-circle" aria-hidden="true"></ha-icon>`
                  : nothing}
              </button>`,
            )}
          </div>`
        : html`<p role="status">No exposed Music Assistant players are available.</p>`}
    </section>`;
  }

  _renderSettings() {
    return html`<section aria-labelledby="settings-title">
      <h2 id="settings-title">Music Settings</h2>
      <div class="setting-row">
        <span>Selected output</span>
        <strong>${this._selectedPlayer ? this._name(this._selectedPlayer) : "None"}</strong>
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
      ${this._renderPlayer()}
    </div>`;
  }

  static styles = css`
    :host{display:block;min-height:100%;color:var(--primary-text-color);background:var(--primary-background-color);font-family:var(--ha-font-family-body,Roboto,"Segoe UI",sans-serif)}
    *{box-sizing:border-box}.page{max-width:1100px;margin:0 auto;padding:20px 18px 130px}header{padding:8px 0 14px}.eyebrow{color:var(--primary-color);font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin:0 0 6px}h1{font-size:30px;line-height:1.2;margin:0}h2{font-size:22px;margin:0 0 10px}nav{display:flex;gap:8px;overflow-x:auto;padding:4px 0 20px}button{cursor:pointer;font:inherit}nav button{border:1px solid var(--divider-color);border-radius:999px;background:var(--card-background-color);color:var(--primary-text-color);padding:10px 17px;min-height:44px;white-space:nowrap}nav button.active{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}button:focus-visible{outline:3px solid var(--primary-color);outline-offset:3px}section{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:16px;padding:20px;min-height:200px}.secondary{color:var(--secondary-text-color);line-height:1.5}.link-button{display:flex;align-items:center;gap:6px;border:0;background:transparent;color:var(--primary-color);padding:12px 0;min-height:44px}.route-list{display:grid;gap:8px;margin-top:18px}.route-row{display:flex;align-items:center;gap:12px;width:100%;padding:12px;border:1px solid var(--divider-color);border-radius:12px;background:var(--secondary-background-color);color:var(--primary-text-color);text-align:left;min-height:64px}.route-row.selected{border-color:var(--primary-color)}.route-copy{display:flex;flex-direction:column;gap:3px;flex:1}.route-copy small{color:var(--secondary-text-color)}.setting-row{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--divider-color);padding:16px 0}.player{position:fixed;bottom:var(--safe-area-inset-bottom,0px);left:var(--ha-sidebar-width,0px);right:0;min-height:78px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 22px;background:var(--card-background-color);border-top:1px solid var(--divider-color);box-shadow:0 -3px 16px #0002}.player.empty{color:var(--secondary-text-color)}.player-copy{min-width:0}.player-title{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.player-actions{display:flex;gap:8px}.player-actions button{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:50%;background:var(--secondary-background-color);color:var(--primary-text-color)}.player-actions button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff)}.player-actions button:disabled{opacity:.5;cursor:not-allowed}.error{color:var(--error-color);padding:12px}ha-icon{--mdc-icon-size:22px}
    @media(max-width:760px){.page{padding:14px 14px 112px}h1{font-size:27px}section{padding:16px}.player{left:0;min-height:68px;padding:8px 12px}.player .secondary{font-size:12px}.player-actions{gap:2px}.player-actions button{width:40px;height:40px}}
  `;
}

if (!customElements.get("ma-mobile-panel")) {
  customElements.define("ma-mobile-panel", MusicAssistantMobilePanel);
}

