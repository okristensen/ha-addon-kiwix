/**
 * Kiwix app card for Home Assistant dashboards.
 *
 * Shows the full Kiwix app (library, catalog and reader) on a dashboard, the same
 * as when it is opened from the sidebar. Home Assistant only serves an app's
 * ingress page to browsers that hold an ingress session cookie, which the
 * frontend creates when an app is opened from the sidebar. This card creates and
 * renews that session itself, so a plain iframe is not enough and not needed.
 *
 * Usage (use a panel view so the card fills the page):
 *
 *   type: custom:kiwix-app-card
 *   app: xxxxxxxx_kiwix   # optional; found automatically when left out
 *
 * Requires an admin user: the Supervisor API is not available to others.
 */
class KiwixAppCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._started = false;
    this._timer = null;
    this._onResize = () => this._fit();
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._started) {
      this._started = true;
      this._start();
    }
  }

  getCardSize() {
    return 12;
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    window.removeEventListener("resize", this._onResize);
    this._started = false;
  }

  async _api(endpoint, method = "get", data) {
    const message = { type: "supervisor/api", endpoint, method };
    if (data) message.data = data;
    const response = await this._hass.callWS(message);
    // Depending on the Home Assistant version the Supervisor envelope is unwrapped or not.
    return response && "result" in response && "data" in response ? response.data : response;
  }

  async _findSlug() {
    if (this._config.app) return this._config.app;
    const { addons } = await this._api("/addons");
    const match = addons.find((addon) => addon.slug.endsWith("_kiwix"));
    if (!match) throw new Error("the Kiwix app is not installed");
    return match.slug;
  }

  async _start() {
    this._render("");
    try {
      const slug = await this._findSlug();
      const info = await this._api(`/addons/${slug}/info`);
      if (!info.ingress_url) throw new Error("the app has no ingress page");

      const { session } = await this._api("/ingress/session", "post");
      this._setCookie(session);
      // Keep the session alive for as long as the card is on screen.
      this._timer = setInterval(() => {
        this._api("/ingress/validate_session", "post", { session }).catch(() => {
          this._api("/ingress/session", "post")
            .then((fresh) => this._setCookie(fresh.session))
            .catch(() => {});
        });
      }, 5 * 60 * 1000);

      this._render(`<iframe src="${info.ingress_url}reader/" allow="fullscreen"></iframe>`);
      window.addEventListener("resize", this._onResize);
      requestAnimationFrame(() => this._fit());
      setTimeout(() => this._fit(), 500);
    } catch (error) {
      this._render(`<p class="error">Could not open Kiwix: ${error.message || error}</p>`);
    }
  }

  // Fill exactly the space below the dashboard header, so the page never scrolls
  // and the top of the reader stays visible.
  _fit() {
    const frame = this.shadowRoot.querySelector("iframe");
    if (!frame) return;
    const top = Math.max(this.getBoundingClientRect().top, 0);
    frame.style.height = `${Math.max(Math.floor(window.innerHeight - top), 200)}px`;
  }

  _setCookie(session) {
    const secure = location.protocol === "https:" ? ";Secure" : "";
    document.cookie = `ingress_session=${session};path=/api/hassio_ingress/;SameSite=Strict${secure}`;
  }

  _render(body) {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; overflow: hidden; }
        iframe {
          display: block;
          width: 100%;
          height: calc(100vh - var(--header-height, 56px) - env(safe-area-inset-top, 0px));
          border: 0;
          background: var(--primary-background-color);
        }
        .error { padding: 16px; color: var(--error-color, #d93025); }
      </style>
      ${body}`;
  }
}

if (!customElements.get("kiwix-app-card")) {
  customElements.define("kiwix-app-card", KiwixAppCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "kiwix-app-card",
  name: "Kiwix",
  description: "The Kiwix app (library, catalog and reader) on a dashboard",
});
