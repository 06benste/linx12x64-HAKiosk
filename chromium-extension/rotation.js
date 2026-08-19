// Screen rotation via a full-page CSS transform — not xrandr. The default
// kiosk is cage (Wayland), which runs no X server at all, so there's no
// xrandr to call. This rotates the rendered page itself; the browser's own
// hit-testing follows the CSS transform, so touch/click coordinates still
// land correctly without any separate input remapping.
//
// Loaded at document_start (manifest.json) so it applies before first paint
// where possible. power-drawer.js (document_idle) calls
// window.__haKioskApplyRotation directly for instant feedback when the user
// taps a rotate button, instead of waiting for the next page load. A
// low-frequency poll below covers the other source of rotation changes:
// auto-rotate.py calling POST /rotate on its own, with nothing else in the
// page to notice — without this, the persisted rotation would be correct
// but the already-loaded kiosk page would just sit there unrotated until
// its next reload.
(() => {
  if (window.__haKioskApplyRotation) return;

  const POWER_BASE = "http://127.0.0.1:17823";
  const STYLE_ID = "ha-kiosk-rotation-style";
  const POLL_INTERVAL_MS = 3000;

  function css(direction) {
    switch (direction) {
      case "inverted":
        return `
          html[data-ha-rotation="inverted"] {
            transform: rotate(180deg);
            transform-origin: center center;
          }`;
      case "right":
        // Rotate 90deg clockwise: swap width/height so the rotated content
        // fills the physical (landscape) screen, then rotate + translate
        // back into place around the top-left corner.
        return `
          html[data-ha-rotation="right"] {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vh;
            height: 100vw;
            overflow: hidden;
            transform-origin: top left;
            transform: rotate(90deg) translateY(-100%);
          }`;
      case "left":
        // Mirror of "right" — rotate 90deg counter-clockwise instead.
        return `
          html[data-ha-rotation="left"] {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vh;
            height: 100vw;
            overflow: hidden;
            transform-origin: top left;
            transform: rotate(-90deg) translateX(-100%);
          }`;
      default:
        return "";
    }
  }

  function apply(direction) {
    const root = document.documentElement;
    if (!root) return;
    if (!direction || direction === "normal") {
      root.removeAttribute("data-ha-rotation");
    } else {
      root.setAttribute("data-ha-rotation", direction);
    }
    let style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement("style");
      style.id = STYLE_ID;
      (document.head || root).appendChild(style);
    }
    style.textContent = css(direction);
  }

  window.__haKioskApplyRotation = apply;

  let known = "normal";

  fetch(`${POWER_BASE}/status`, { cache: "no-store" })
    .then((r) => r.json())
    .then((d) => {
      known = (d && d.rotation) || "normal";
      apply(known);
    })
    .catch(() => {});

  setInterval(() => {
    fetch(`${POWER_BASE}/status`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const rotation = (d && d.rotation) || "normal";
        if (rotation !== known) {
          known = rotation;
          apply(rotation);
        }
      })
      .catch(() => {});
  }, POLL_INTERVAL_MS);
})();
