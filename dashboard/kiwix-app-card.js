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
 *   app: xxxxxxxx_kiwix   # optional; found automatically when left out (needs an admin)
 *   apps_card: true       # optional; shows the "Flere apps" card below the front page only
 */
class KiwixAppCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._started = false;
    this._timer = null;
    this._apps = null;
    this._onResize = () => this._fit();
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (this._apps) this._apps.hass = hass;
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
    this._apps = null;
    window.removeEventListener("resize", this._onResize);
    if (window.visualViewport) window.visualViewport.removeEventListener("resize", this._onResize);
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
      if (window.visualViewport) window.visualViewport.addEventListener("resize", this._onResize);
      this.shadowRoot.querySelector("iframe").addEventListener("load", () => this._lock());
      requestAnimationFrame(() => this._fit());
      setTimeout(() => this._fit(), 500);
      this._watchPage();
    } catch (error) {
      this._render(`<p class="error">Could not open Kiwix: ${error.message || error}</p>`);
    }
  }

  // The "Flere apps" card (config: apps_card: true) belongs on the front page only,
  // so it is created here and shown while the reader is on its front page.
  async _watchPage() {
    const frame = this.shadowRoot.querySelector("iframe");
    if (!frame || !this._config.apps_card) return;
    const box = document.createElement("div");
    box.hidden = true;
    this._box = box;
    this.shadowRoot.appendChild(box);
    try {
      const helpers = await window.loadCardHelpers();
      this._apps = await helpers.createCardElement({ type: "custom:apps-kort", ...(this._config.apps_config || {}) });
      this._apps.hass = this._hass;
      box.appendChild(this._apps);
    } catch (error) {
      return;
    }
    const check = () => {
      let path = "";
      try {
        path = frame.contentWindow.location.pathname;
      } catch (error) {
        /* not readable: treat as another page */
      }
      box.hidden = !/\/reader\/?$/.test(path);
      watchBody();
      this._fit();
    };
    // On the front page the reader is as tall as its content and this card
    // scrolls, so "Flere apps" ends up at the very bottom of the page.
    if (window.ResizeObserver) new ResizeObserver(() => this._fit()).observe(box);
    const watchBody = () => {
      if (this._bodyObserver) this._bodyObserver.disconnect();
      try {
        if (window.ResizeObserver) {
          this._bodyObserver = new ResizeObserver(() => this._fit());
          this._bodyObserver.observe(frame.contentDocument.body);
        }
      } catch (error) {
        /* not readable */
      }
    };
    frame.addEventListener("load", check);
    check();
  }

  // The size of the device's safe area (notch, home indicator) on one side, in px.
  _inset(side) {
    const probe = document.createElement("div");
    probe.style.cssText = `position:fixed;visibility:hidden;pointer-events:none;padding-${side}:env(safe-area-inset-${side},0px)`;
    document.body.appendChild(probe);
    const px = parseFloat(getComputedStyle(probe)[`padding${side[0].toUpperCase()}${side.slice(1)}`]) || 0;
    probe.remove();
    return px;
  }

  // Stop the page inside the frame from bouncing or handing its scroll on to the
  // dashboard behind it, so nothing but the text moves when the user scrolls.
  _lock() {
    try {
      const doc = this.shadowRoot.querySelector("iframe").contentDocument;
      // The frame reaches the bottom edge of the screen, so the pages inside
      // are told how much of it the home indicator covers (env() is 0 in a frame).
      doc.documentElement.style.setProperty("--kiwix-sab", `${this._inset("bottom")}px`);
      doc.documentElement.style.overscrollBehavior = "none";
      if (doc.body) doc.body.style.overscrollBehavior = "none";
    } catch (error) {
      /* not readable */
    }
  }

  // Pin the card to the screen, from just below the dashboard header (or the very
  // top when the header is hidden) down to the bottom edge, keeping clear of the
  // status bar (the pages inside keep clear of the home indicator themselves). Being fixed it cannot be scrolled away or
  // leave a strip of the dashboard showing, however the page behind it behaves.
  // The card itself only scrolls on the front page, where the reader takes the
  // height of its content with "Flere apps" underneath; articles scroll inside
  // the frame and nothing else moves.
  _fit() {
    const frame = this.shadowRoot.querySelector("iframe");
    if (!frame) return;
    if (this._top0 === undefined) {
      const rect = this.getBoundingClientRect();
      this._top0 = Math.max(rect.top, 0);
      this._left0 = Math.max(rect.left, 0);
    }
    const front = !!(this._box && !this._box.hidden);
    const padTop = this._top0 < 1 ? this._inset("top") : 0;
    const padBottom = 0;
    this.classList.toggle("front", front);
    Object.assign(this.style, {
      position: "fixed",
      top: `${this._top0}px`,
      left: `${this._left0}px`,
      right: "0",
      bottom: "0",
      height: "auto",
      padding: `${padTop}px 0 ${padBottom}px`,
    });
    const room = Math.max(this.clientHeight - padTop - padBottom, 200);
    let height = room;
    if (front) {
      let content = 0;
      try {
        content = frame.contentDocument.body.offsetHeight;
      } catch (error) {
        /* not readable */
      }
      height = Math.max(content, room - Math.ceil(this._box.getBoundingClientRect().height));
    }
    frame.style.height = `${height}px`;
  }

  _setCookie(session) {
    const secure = location.protocol === "https:" ? ";Secure" : "";
    document.cookie = `ingress_session=${session};path=/api/hassio_ingress/;SameSite=Strict${secure}`;
  }

  _render(body) {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block; box-sizing: border-box; overflow-x: hidden; overflow-y: hidden;
          overscroll-behavior: none; background: var(--kiwix-bg, #f3f5f8);
        }
        @media (prefers-color-scheme: dark) { :host { --kiwix-bg: #0f1216; } }
        :host(.front) { overflow-y: auto; -webkit-overflow-scrolling: touch; }
        iframe {
          display: block;
          width: 100%;
          height: calc(100vh - var(--header-height, 56px) - env(safe-area-inset-top, 0px));
          border: 0;
          background: var(--kiwix-bg, #f3f5f8);
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
