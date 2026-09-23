import { LitElement, css, html, nothing } from "lit";
import { loadSendspinClientIdentity, SendspinPlayer } from "@sendspin/sendspin-js";

function headerActions() {
  const root = document.querySelector("home-assistant")?.shadowRoot;
  if (!root) return [];
  const roots = [root];
  for (let i = 0; i < roots.length && i < 120; i++) {
    for (const element of roots[i].querySelectorAll("*")) {
      if (element.shadowRoot) roots.push(element.shadowRoot);
      if (element.localName !== "ha-top-app-bar-fixed" && element.localName !== "app-header") continue;
      const rect = element.getBoundingClientRect();
      if (!rect.width || rect.top >= 120 || rect.bottom <= 0) continue;
      const actions = [...element.querySelectorAll('[slot="actionItems"]')]
        .map((item) => item.getBoundingClientRect())
        .filter((item) => item.width > 0 && item.top < 120);
      if (actions.length) return actions;
    }
  }
  return [];
}

class MusicAssistantBubble extends LitElement {
  static properties = {
    _open: { state: true }, _ready: { state: true },
    _playing: { state: true }, _item: { state: true }, _error: { state: true },
  };

  constructor() {
    super();
    this._open = false;
    this._ready = false;
    this._playing = false;
    this._item = undefined;
    this._error = "";
    this._identity = loadSendspinClientIdentity();
    this._onNavigate = () => requestAnimationFrame(() => this._place());
    this._onPlayLocal = (event) => this._playLocal(event.detail);
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("location-changed", this._onNavigate);
    window.addEventListener("popstate", this._onNavigate);
    window.addEventListener("resize", this._onNavigate);
    window.addEventListener("ma-mobile-play-local", this._onPlayLocal);
    this._timer = window.setInterval(() => this._syncHass(), 2000);
    this._syncHass();
    requestAnimationFrame(() => this._place());
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    clearTimeout(this._retryTimer);
    this._player?.disconnect("user_request");
    this._socket?.close();
    window.removeEventListener("location-changed", this._onNavigate);
    window.removeEventListener("popstate", this._onNavigate);
    window.removeEventListener("resize", this._onNavigate);
    window.removeEventListener("ma-mobile-play-local", this._onPlayLocal);
    super.disconnectedCallback();
  }

  async _syncHass() {
    const hass = document.querySelector("home-assistant")?.hass;
    if (!hass?.callWS || this._connecting) return;
    this._hass = hass;
    if (this._entryId) {
      if (!this._ready) await this._connect();
      return;
    }
    try {
      const entries = await hass.callWS({ type: "config_entries/get", domain: "music_assistant" });
      const entry = entries.find((candidate) => candidate.state === "loaded");
      if (!entry) return;
      this._entryId = entry.entry_id;
      await this._connect();
    } catch (error) {
      this._error = error?.message || "Cannot prepare local playback.";
    }
  }

  async _connect() {
    if (this._connecting || !this._hass || !this._entryId) return;
    this._connecting = true;
    this._ready = false;
    clearTimeout(this._retryTimer);
    this._player?.disconnect("restart");
    try {
      const path = `/api/music_assistant_mobile/sendspin/${this._entryId}`;
      const signed = await this._hass.callWS({ type: "auth/sign_path", path, expires: 60 });
      const url = new URL(signed.path, window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      this._socket = socket;
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("Local player connection timed out.")), 12000);
        socket.onopen = () => socket.send(JSON.stringify({ type: "auth", client_id: this._identity.clientId }));
        socket.onmessage = (event) => {
          try {
            if (JSON.parse(event.data).type !== "auth_ok") throw new Error("Local player authentication failed.");
            clearTimeout(timeout);
            resolve();
          } catch (error) {
            clearTimeout(timeout);
            reject(error);
          }
        };
        socket.onerror = () => { clearTimeout(timeout); reject(new Error("Local player connection failed.")); };
        socket.onclose = () => { clearTimeout(timeout); reject(new Error("Local player connection closed.")); };
      });
      socket.onmessage = null;
      this._player = new SendspinPlayer({
        webSocket: socket,
        clientName: "Home Assistant browser",
        productName: "Web Player",
        codecs: ["opus", "flac"],
        correctionMode: "quality-local",
        requiredLeadTimeMs: 250,
        minBufferMs: 500,
        onStateChange: (state) => {
          this._playing = state.isPlaying;
          if (state.playerState === "error") this._error = "Local audio cannot be decoded.";
          if (navigator.mediaSession) navigator.mediaSession.playbackState = state.isPlaying ? "playing" : "paused";
        },
      });
      await this._player.connect();
      this._ready = true;
      this._error = "";
      this._registerMediaKeys();
      socket.addEventListener("close", () => {
        if (!this.isConnected) return;
        this._ready = false;
        this._retryTimer = setTimeout(() => this._connect(), 3000);
      });
    } catch (error) {
      this._socket?.close();
      this._error = error?.message || "Local player could not connect.";
    } finally {
      this._connecting = false;
    }
  }

  _registerMediaKeys() {
    if (!navigator.mediaSession) return;
    for (const [action, command] of Object.entries({ play: "play", pause: "pause", nexttrack: "next", previoustrack: "previous" })) {
      navigator.mediaSession.setActionHandler(action, () => this._control(command));
    }
  }

  _place() {
    const actions = headerActions();
    const first = actions.length ? Math.min(...actions.map((rect) => rect.left)) : window.innerWidth - 52;
    const top = actions.length ? actions[0].top + (actions[0].height - 40) / 2 : 4;
    this.style.left = `${Math.max(4, Math.min(window.innerWidth - 44, first - 44))}px`;
    this.style.top = `${Math.max(4, top)}px`;
    this.style.setProperty("--ma-popover-top", `${Math.max(50, top + 46)}px`);
  }

  async _playLocal(item) {
    if (!this._ready || !this._player || !this._identity.pairingToken) {
      this._error = "Local player is connecting. Try again in a moment.";
      this._open = true;
      return;
    }
    // Start unlock in the original click handler, before awaiting any network call.
    const unlock = this._player.unlock();
    this._item = item;
    this._open = true;
    this._error = "";
    try {
      await unlock;
      await this._hass.callService("music_assistant", "mobile_play", {
        config_entry_id: this._entryId,
        client_id: this._identity.clientId,
        pairing_token: this._identity.pairingToken,
        media_id: item.uri,
      });
      if (navigator.mediaSession) {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: item.name,
          artist: item.artists?.map((artist) => artist.name).join(", ") || "Music Assistant",
          artwork: item.image ? [{ src: item.image }] : [],
        });
      }
    } catch (error) {
      this._error = error?.message || "This item could not be played locally.";
    }
  }

  async _control(command) {
    if (!this._ready || !this._identity.pairingToken) return;
    this._error = "";
    try {
      await this._hass.callService("music_assistant", "mobile_control", {
        config_entry_id: this._entryId,
        client_id: this._identity.clientId,
        pairing_token: this._identity.pairingToken,
        command,
      });
      if (command === "next" || command === "previous") this._item = undefined;
    } catch (error) {
      this._error = error?.message || "Local playback could not be controlled.";
    }
  }

  render() {
    return html`<button class="bubble" type="button" aria-label="Local music player"
      aria-expanded=${this._open} @click=${() => { this._open = !this._open; this._place(); }}>
      <ha-icon icon=${this._playing ? "mdi:music-circle" : "mdi:music-note"}></ha-icon>
    </button>
    ${this._open ? html`<div class="popover" role="region" aria-label="Local music player">
      <div class="title"><strong>This browser</strong><button type="button" aria-label="Close player controls" @click=${() => this._open = false}><ha-icon icon="mdi:close"></ha-icon></button></div>
      <p class="status" role="status">${this._ready ? this._playing ? "Playing here" : "Ready to play here" : "Connecting local player…"}</p>
      <div class="track"><strong>${this._item?.name || "Music Assistant"}</strong><span>${this._item?.artists?.map((artist) => artist.name).join(", ") || "Local browser audio"}</span></div>
      <div class="controls">
        <button type="button" aria-label="Previous track" ?disabled=${!this._ready} @click=${() => this._control("previous")}><ha-icon icon="mdi:skip-previous"></ha-icon></button>
        <button type="button" aria-label=${this._playing ? "Pause" : "Play"} ?disabled=${!this._ready} @click=${() => this._control(this._playing ? "pause" : "play")}><ha-icon icon=${this._playing ? "mdi:pause" : "mdi:play"}></ha-icon></button>
        <button type="button" aria-label="Next track" ?disabled=${!this._ready} @click=${() => this._control("next")}><ha-icon icon="mdi:skip-next"></ha-icon></button>
      </div>
      ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
      <a href="/music-assistant-mobile">Open Music Library</a>
    </div>` : nothing}`;
  }

  static styles = css`
    :host{position:fixed;z-index:6;color:var(--primary-text-color);font-family:var(--ha-font-family-body,Roboto,sans-serif)}*{box-sizing:border-box}button{font:inherit;cursor:pointer;color:inherit}button:focus-visible,a:focus-visible{outline:3px solid var(--primary-color);outline-offset:2px}.bubble{display:grid;place-items:center;width:40px;height:40px;border:0;border-radius:50%;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff)}.bubble ha-icon{--mdc-icon-size:25px}.popover{position:fixed;top:var(--ma-popover-top,50px);right:8px;width:min(320px,calc(100vw - 16px));padding:16px;border:1px solid var(--divider-color);border-radius:14px;background:var(--card-background-color);box-shadow:0 8px 28px #0004}.title{display:flex;align-items:center;justify-content:space-between}.title button,.controls button{display:grid;place-items:center;width:44px;height:44px;border:0;background:transparent}.track{display:flex;flex-direction:column;gap:4px;margin:12px 0}.track span,.status{color:var(--secondary-text-color)}.controls{display:flex;justify-content:center;gap:8px;margin:12px 0}.controls button{border-radius:50%;background:var(--secondary-background-color)}.controls button:disabled{opacity:.5}.error{color:var(--error-color)}a{display:block;padding:10px 0;color:var(--primary-color)}
  `;
}

if (!customElements.get("ma-mobile-bubble")) customElements.define("ma-mobile-bubble", MusicAssistantBubble);
function mountBubble() {
  if (!document.querySelector("ma-mobile-bubble") && document.body) document.body.appendChild(document.createElement("ma-mobile-bubble"));
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountBubble, { once: true });
else mountBubble();

