// Ensure HA Kiosk Mode is active (hide sidebar/header) on this panel.
(() => {
  if (window.__haKioskModeEnsure) return;
  window.__haKioskModeEnsure = true;

  const HIDE_CSS = `
    /* Keep the HA left sidebar / header out of the kiosk UI */
    ha-sidebar,
    ha-drawer ha-sidebar,
    aside.sidebar,
    .mdc-drawer,
    [slot="sidebar"] {
      display: none !important;
      width: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      visibility: hidden !important;
      pointer-events: none !important;
    }
    home-assistant-main,
    ha-drawer,
    :host([expanded]) ha-drawer {
      --mdc-drawer-width: 0px !important;
      --ha-drawer-width: 0px !important;
    }
    .header, .toolbar ha-menu-button, ha-menu-button,
    app-toolbar ha-menu-button, ha-top-app-bar-fixed ha-menu-button {
      display: none !important;
    }
  `;

  function ensureHideCss() {
    if (document.getElementById("ha-kiosk-sidebar-fallback")) return;
    const style = document.createElement("style");
    style.id = "ha-kiosk-sidebar-fallback";
    style.textContent = HIDE_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function ensureQueryFlag() {
    const s = location.search || "";
    if (/(?:^\?|&)(kiosk|hide_sidebar|hide_header)(?:&|=|$)/.test(s)) return false;
    const join = s ? "&" : "?";
    const next = location.pathname + s + join + "kiosk" + (location.hash || "");
    history.replaceState(null, "", next);
    return true;
  }

  function injectModule() {
    if (document.querySelector("script[data-ha-kiosk-mode]")) return;
    const s = document.createElement("script");
    s.type = "module";
    s.dataset.haKioskMode = "1";
    s.src = "/hacsfiles/kiosk-mode/kiosk-mode.js";
    (document.head || document.documentElement).appendChild(s);
  }

  ensureHideCss();
  const rewrote = ensureQueryFlag();
  injectModule();
  // Re-apply after HA paints (shadow roots / late drawers)
  const kick = () => ensureHideCss();
  document.addEventListener("DOMContentLoaded", kick, { once: true });
  setTimeout(kick, 500);
  setTimeout(kick, 2000);

  if (rewrote) {
    try {
      if (!sessionStorage.getItem("ha-kiosk-mode-reloaded")) {
        sessionStorage.setItem("ha-kiosk-mode-reloaded", "1");
        location.reload();
      }
    } catch (_) {
      /* ignore */
    }
  }
})();
