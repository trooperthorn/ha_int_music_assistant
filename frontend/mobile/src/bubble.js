import { LitElement, css, html, nothing } from "lit";

const STORAGE_KEY = "ma-mobile-selected-player";

function findHeaderActions() {
  const root = document.querySelector("home-assistant")?.shadowRoot;
  if (!root) return [];
  const roots = [root];
  const headers = [];
  for (let index = 0; index < roots.length && index < 120; index++) {
    for (const element of roots[index].querySelectorAll("*")) {
      if (element.shadowRoot) roots.push(element.shadowRoot);
      if (element.localName === "ha-top-app-bar-fixed" || element.localName === "app-header") {
        const rect = element.getBoundingClientRect();
        if (rect.width > 0 && rect.top < 120 && rect.bottom > 0) headers.push(element);
      }
    }
  }
  for (const header of headers) {
    const actions = [...header.querySelectorAll('[slot="actionItems"]')]
      .map((element) => element.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.top < 120);
    if (actions.length) return actions;
  }
  return [];
}

class MusicAssistantBubble extends LitElement {
  static properties = {
    _open: { state: true },
    _players: { state: true },
    _selectedId: { state: true },
    _error: { state: true },
  };

  constructor() {
    super();
    this._open = false;
    this._players = {};
    this._selectedId = sessionStorage.getItem(STORAGE_KEY) || "";
    this._error = "";
    this._connection = undefined;
    this._unsubscribe = undefined;
    this._onSelected = (event) => {
      this._selectedId = event.detail;
    };
    this._onNavigate = () => requestAnimationFrame(() => this._place());
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("ma-mobile-player-selected", this._onSelected);
    window.addEventListener("location-changed", this._onNavigate);
    window.addEventListener("popstate", this._onNavigate);
    window.addEventListener("resize", this._onNavigate);
    this._timer = window.setInterval(() => this._syncHass(), 2000);
    this._syncHass();
    requestAnimationFrame(() => this._place());
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._unsubscribe?.();
    window.removeEventListener("ma-mobile-player-selected", this._onSelected);
    window.removeEventListener("location-changed", this._onNavigate);
    window.removeEventListener("popstate", this._onNavigate);
    window.removeEventListener("resize", this._onNavigate);
    super.disconnectedCallback();
  }

  async _syncHass() {
    const hass = document.querySelector("home-assistant")?.hass;
    if (!hass?.states) return;
    this._hass = hass;
    if (hass.connection === this._connection) return;
    this._unsubscribe?.();
    this._connection = hass.connection;
    this._players = Object.fromEntries(
      Object.values(hass.states)
        .filter((state) => state.entity_id.startsWith("media_player.") && typeof state.attributes?.mass_player_type === "string")
        .map((state) => [state.entity_id, state]),
    );
    try {
      this._unsubscribe = await hass.connection.subscribeEvents((event) => {
        const { entity_id: entityId, new_state: state } = event.data;
        if (!entityId?.startsWith("media_player.")) return;
        const players = { ...this._players };
        if (state && typeof state.attributes?.mass_player_type === "string") {
          players[entityId] = state;
        } else {
          delete players[entityId];
        }
        this._players = players;
      }, "state_changed");
    } catch (error) {
      this._error = error?.message || "Player updates are unavailable.";
    }
    this._place();
  }

  _place() {
    const actions = findHeaderActions();
    const first = actions.length ? Math.min(...actions.map((rect) => rect.left)) : window.innerWidth - 52;
    const top = actions.length ? actions[0].top + (actions[0].height - 40) / 2 : 4;
    const left = Math.max(4, Math.min(window.innerWidth - 44, first - 44));
    this.style.left = `${left}px`;
    this.style.top = `${Math.max(4, top)}px`;
    this.style.setProperty("--ma-popover-top", `${Math.max(50, top + 46)}px`);
  }

  get _selectedPlayer() {
    return this._players[this._selectedId] || Object.values(this._players)[0];
  }

  _selectPlayer(event) {
    this._selectedId = event.target.value;
    sessionStorage.setItem(STORAGE_KEY, this._selectedId);
    window.dispatchEvent(new CustomEvent("ma-mobile-player-selected", { detail: this._selectedId }));
  }

  async _control(service) {
    const player = this._selectedPlayer;
    if (!player || !this._hass) return;
    this._error = "";
    try {
      await this._hass.callService("media_player", service, { entity_id: player.entity_id });
    } catch (error) {
      this._error = error?.message || "The player could not be controlled.";
    }
  }

  render() {
    const player = this._selectedPlayer;
    const playing = player?.state === "playing";
    return html`<button class="bubble" type="button" aria-label="Music player"
      aria-expanded=${this._open} @click=${() => { this._open = !this._open; this._place(); }}>
      <ha-icon icon=${playing ? "mdi:music-circle" : "mdi:music-note"}></ha-icon>
    </button>
    ${this._open ? html`<div class="popover" role="region" aria-label="Music Assistant player">
      <div class="title"><strong>Music Assistant</strong><button type="button" aria-label="Close music player" @click=${() => this._open = false}><ha-icon icon="mdi:close"></ha-icon></button></div>
      ${player ? html`<div class="track"><strong>${player.attributes.media_title || "Nothing playing"}</strong><span>${player.attributes.media_artist || player.attributes.friendly_name || player.entity_id}</span></div>
        <label>Output<select .value=${player.entity_id} @change=${this._selectPlayer}>
          ${Object.values(this._players).map((item) => html`<option value=${item.entity_id}>${item.attributes.friendly_name || item.entity_id}</option>`)}
        </select></label>
        <div class="controls">
          <button type="button" aria-label="Previous track" @click=${() => this._control("media_previous_track")}><ha-icon icon="mdi:skip-previous"></ha-icon></button>
          <button type="button" aria-label=${playing ? "Pause" : "Play"} @click=${() => this._control(playing ? "media_pause" : "media_play")}><ha-icon icon=${playing ? "mdi:pause" : "mdi:play"}></ha-icon></button>
          <button type="button" aria-label="Next track" @click=${() => this._control("media_next_track")}><ha-icon icon="mdi:skip-next"></ha-icon></button>
        </div>` : html`<p>No Music Assistant player is exposed to Home Assistant.</p>`}
      ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
      <a href="/music-assistant-mobile">Open Music Library</a>
    </div>` : nothing}`;
  }

  static styles = css`
    :host{position:fixed;z-index:6;color:var(--primary-text-color);font-family:var(--ha-font-family-body,Roboto,sans-serif)}
    *{box-sizing:border-box}button{font:inherit;cursor:pointer;color:inherit}button:focus-visible,a:focus-visible,select:focus-visible{outline:3px solid var(--primary-color);outline-offset:2px}.bubble{display:grid;place-items:center;width:40px;height:40px;border:0;border-radius:50%;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff)}.bubble ha-icon{--mdc-icon-size:25px}.popover{position:fixed;top:var(--ma-popover-top,50px);right:8px;width:min(320px,calc(100vw - 16px));padding:16px;border:1px solid var(--divider-color);border-radius:14px;background:var(--card-background-color);box-shadow:0 8px 28px #0004}.title{display:flex;align-items:center;justify-content:space-between}.title button,.controls button{display:grid;place-items:center;width:44px;height:44px;border:0;background:transparent}.track{display:flex;flex-direction:column;gap:4px;margin:12px 0}.track span{color:var(--secondary-text-color)}label{display:grid;gap:6px;font-size:13px}select{width:100%;min-height:44px;padding:6px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color)}.controls{display:flex;justify-content:center;gap:8px;margin:12px 0}.controls button{border-radius:50%;background:var(--secondary-background-color)}.error{color:var(--error-color)}a{display:block;padding:10px 0;color:var(--primary-color)}
  `;
}

if (!customElements.get("ma-mobile-bubble")) {
  customElements.define("ma-mobile-bubble", MusicAssistantBubble);
}

function mountBubble() {
  if (!document.querySelector("ma-mobile-bubble") && document.body) {
    document.body.appendChild(document.createElement("ma-mobile-bubble"));
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountBubble, { once: true });
} else {
  mountBubble();
}

