// Right-edge control drawer for HA kiosk tablet.
(() => {
  if (window.__haKioskPowerDrawer) return;
  window.__haKioskPowerDrawer = true;

  const ROOT_ID = "ha-kiosk-power-drawer-root";
  if (document.getElementById(ROOT_ID)) return;

  const POWER_BASE = "http://127.0.0.1:17823";
  const PANEL_WIDTH = "min(300px, 82vw)";

  const host = document.createElement("div");
  host.id = ROOT_ID;
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host, * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
      .tab {
        pointer-events: auto;
        position: fixed;
        top: 50%;
        right: 0;
        transform: translateY(-50%);
        width: 40px;
        height: 96px;
        border: 0;
        border-radius: 12px 0 0 12px;
        background: rgba(18, 22, 26, 0.88);
        color: #e8ecf0;
        font-size: 22px;
        line-height: 1;
        cursor: pointer;
        box-shadow: -2px 0 12px rgba(0,0,0,0.28);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        transition: background 0.15s ease, right 0.22s ease;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .tab:active { background: rgba(18, 22, 26, 0.98); }
      .tab.has-update::after {
        content: "";
        position: absolute;
        top: 10px;
        right: 8px;
        width: 11px;
        height: 11px;
        border-radius: 50%;
        background: #e05a4f;
        border: 2px solid rgba(18, 22, 26, 0.92);
      }
      .panel {
        pointer-events: auto;
        position: fixed;
        top: 0;
        right: 0;
        height: 100vh;
        width: ${PANEL_WIDTH};
        background: rgba(14, 17, 21, 0.97);
        color: #eef1f4;
        padding: 14px 14px 18px;
        transform: translateX(105%);
        transition: transform 0.22s ease;
        box-shadow: -8px 0 28px rgba(0,0,0,0.35);
        display: flex;
        flex-direction: column;
        gap: 8px;
        z-index: 1;
        overflow: auto;
        -webkit-overflow-scrolling: touch;
      }
      .panel.open { transform: translateX(0); }
      .title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 2px 2px 6px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 2px;
      }
      .title strong {
        font-size: 15px;
        font-weight: 650;
        letter-spacing: 0.01em;
      }
      .pill {
        font-size: 11px;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 999px;
        background: rgba(255,255,255,0.08);
        opacity: 0.9;
      }
      .pill.ok { background: rgba(61,190,122,0.22); color: #8fe0b4; }
      .pill.bad { background: rgba(224,90,79,0.22); color: #ffb0a8; }
      .info {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px;
        padding: 10px 11px;
        font-size: 12.5px;
        line-height: 1.4;
        display: grid;
        gap: 6px;
      }
      .info .primary {
        font-size: 13.5px;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        gap: 8px;
        align-items: baseline;
      }
      .info .meta {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        opacity: 0.78;
      }
      .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        white-space: nowrap;
      }
      .chip.warn {
        background: rgba(165,106,28,0.35);
        color: #ffd699;
        border-radius: 999px;
        padding: 2px 8px;
        opacity: 1;
      }
      .chip.bad {
        background: rgba(224,90,79,0.28);
        color: #ffb0a8;
        border-radius: 999px;
        padding: 2px 8px;
        opacity: 1;
        animation: chip-pulse 1.6s ease-in-out infinite;
      }
      @keyframes chip-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.55; }
      }
      .heading {
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        opacity: 0.55;
        margin: 6px 2px 0;
      }
      .row-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
      .stack { display: grid; gap: 8px; }
      .btn {
        appearance: none;
        border: 0;
        border-radius: 11px;
        min-height: 44px;
        padding: 9px 10px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        color: #fff;
        background: #2f6fed;
        transition: transform 0.1s ease, filter 0.15s ease;
      }
      .btn.secondary { background: #343e4a; }
      .btn.danger { background: #b53a2f; }
      .btn.warn { background: #a56a1c; }
      .btn.preset {
        min-height: 40px;
        font-size: 13px;
        background: #2a333d;
      }
      .btn:active:not(:disabled) { transform: scale(0.97); filter: brightness(0.92); }
      .btn:disabled { opacity: 0.55; cursor: wait; }
      .slider-wrap { display: grid; gap: 6px; }
      .slider-wrap .row {
        display: flex;
        justify-content: space-between;
        font-size: 13px;
        opacity: 0.9;
      }
      .slider-wrap input[type=range] {
        width: 100%;
        accent-color: #2f6fed;
        height: 40px;
        margin: 0;
      }
      .setup-link {
        display: grid;
        gap: 3px;
        text-align: left;
      }
      .setup-link .caption {
        font-size: 11px;
        font-weight: 500;
        opacity: 0.75;
        color: #cfe0ff;
      }
      details.more {
        border-top: 1px solid rgba(255,255,255,0.08);
        margin-top: 4px;
        padding-top: 6px;
      }
      details.more > summary {
        list-style: none;
        cursor: pointer;
        font-size: 12px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        opacity: 0.6;
        padding: 8px 2px;
        user-select: none;
        min-height: 36px;
        display: flex;
        align-items: center;
      }
      details.more > summary::-webkit-details-marker { display: none; }
      details.more > summary::after { content: " ▾"; opacity: 0.7; }
      details.more[open] > summary::after { content: " ▴"; }
      details.more .body {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-top: 4px;
      }
      .status {
        min-height: 1.1em;
        font-size: 12px;
        color: #e2c07a;
      }
      .backdrop {
        pointer-events: none;
        position: fixed;
        inset: 0;
        background: transparent;
        opacity: 0;
        transition: opacity 0.22s ease;
      }
      .backdrop.open {
        pointer-events: auto;
        background: rgba(0,0,0,0.28);
        opacity: 1;
      }
      .cam-overlay {
        pointer-events: auto;
        position: fixed;
        inset: 0;
        z-index: 5;
        background: #0e1115;
        display: none;
      }
      .cam-overlay.open { display: block; }
      .cam-overlay iframe {
        border: 0;
        width: 100%;
        height: 100%;
      }
      .overlay-status {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 28px;
        text-align: center;
        color: #ffb0a8;
        font-size: 15px;
        line-height: 1.5;
        white-space: pre-line;
      }
      .overlay-status.hidden { display: none; }
      .overlay-close {
        position: fixed;
        top: 10px;
        right: 10px;
        z-index: 6;
        appearance: none;
        border: 0;
        border-radius: 999px;
        min-height: 40px;
        padding: 0 16px;
        font-size: 13px;
        font-weight: 650;
        color: #fff;
        background: rgba(181, 58, 47, 0.88);
        backdrop-filter: blur(4px);
        cursor: pointer;
      }
    </style>
    <div class="backdrop"></div>
    <aside class="panel">
      <div class="title">
        <strong>Tablet</strong>
        <span class="pill" id="ha-pill">…</span>
      </div>
      <div class="info" id="info">
        <div class="meta">Loading…</div>
      </div>

      <div class="heading">Display</div>
      <div class="slider-wrap">
        <div class="row"><span>Brightness</span><span id="bright-label">—</span></div>
        <input id="brightness" type="range" min="5" max="100" step="5" value="80" />
      </div>
      <div class="row-btns">
        <button class="btn preset" data-action="night-on" type="button">Night</button>
        <button class="btn preset" data-action="night-off" type="button">Day</button>
      </div>
      <div class="row-btns">
        <button class="btn warn" data-action="display-off" type="button">Blank</button>
        <button class="btn" data-action="display-on" type="button">Wake</button>
      </div>

      <div class="heading">Dashboard</div>
      <div class="row-btns">
        <button class="btn" data-action="refresh" type="button">Refresh</button>
        <button class="btn secondary" data-action="chromium-restart" type="button">Restart display</button>
      </div>

      <div class="stack">
        <button class="btn secondary setup-link" id="btn-tablet-setup" type="button">
          <span>Tablet Setup</span>
          <span class="caption">Camera, charge LED, rotation, Wi‑Fi &amp; more</span>
        </button>
      </div>

      <details class="more">
        <summary>More</summary>
        <div class="body">
          <div class="heading">Maintenance</div>
          <div class="stack">
            <button class="btn warn" data-action="clear-cache" data-confirm="Clear Chromium cache and restart the display?" type="button">Clear cache</button>
            <button class="btn secondary" data-action="reboot" data-confirm="Restart this tablet?" type="button">Restart tablet</button>
            <button class="btn danger" data-action="shutdown" data-confirm="Shut down this tablet?" type="button">Shut down</button>
          </div>
        </div>
      </details>

      <div class="status" aria-live="polite"></div>
    </aside>
    <button class="tab" type="button" aria-label="Open tablet controls" title="Controls">‹</button>
    <div class="cam-overlay" id="cam-overlay" hidden>
      <button class="overlay-close" id="overlay-close" type="button">X Exit to kiosk screen</button>
      <div class="overlay-status hidden" id="overlay-status"></div>
      <iframe title="Tablet Setup" allow="autoplay"></iframe>
    </div>
  `;

  const tab = shadow.querySelector(".tab");
  const panel = shadow.querySelector(".panel");
  const backdrop = shadow.querySelector(".backdrop");
  const camOverlay = shadow.querySelector("#cam-overlay");
  const camFrame = camOverlay.querySelector("iframe");
  const overlayStatus = shadow.querySelector("#overlay-status");
  const overlayClose = shadow.querySelector("#overlay-close");
  const statusEl = shadow.querySelector(".status");
  const info = shadow.querySelector("#info");
  const haPill = shadow.querySelector("#ha-pill");
  const bright = shadow.querySelector("#brightness");
  const brightLabel = shadow.querySelector("#bright-label");
  const btnTabletSetup = shadow.querySelector("#btn-tablet-setup");
  const buttons = shadow.querySelectorAll(".btn");
  let open = false;
  let busy = false;
  let statusTimer = null;
  let updateAvailable = false;
  const SETUP_BASE = "http://127.0.0.1:17825";
  // Home Assistant / Wi-Fi / MQTT / Cameras / General all live as tabs on
  // one setup page now — this is the drawer's single entry point into all
  // of it. Opens straight to General (camera/charge-LED/rotation) since
  // that's what this button is used for day-to-day now that those moved
  // out of the drawer itself; the other tabs are one click away — except
  // when the update bubble is showing, where jumping straight to Updates
  // saves the detour.
  function setupUrl() {
    return SETUP_BASE + "/setup?embed=1&section=" + (updateAvailable ? "updates" : "general");
  }

  // Full-screen overlay/iframe used to show the setup page without leaving
  // the kiosk. "done" messages from inside it close the overlay.
  let overlayDoneType = null;

  async function checkReachable(base) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 4000);
    try {
      const res = await fetch(base + "/health", { cache: "no-store", signal: ctl.signal });
      return res.ok;
    } catch (_) {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function openOverlay(url, doneType, healthBase) {
    setOpen(false);
    overlayDoneType = doneType;
    camOverlay.hidden = false;
    camOverlay.classList.add("open");
    camFrame.style.visibility = "hidden";
    overlayStatus.classList.remove("hidden");
    overlayStatus.textContent = "Checking…";

    if (healthBase && !(await checkReachable(healthBase))) {
      overlayStatus.textContent =
        "Not reachable.\n\nThe service behind this screen isn't responding on this tablet.\n" +
        "Check on the tablet: systemctl status ha-kiosk-setup.service";
      return;
    }

    overlayStatus.classList.add("hidden");
    camFrame.style.visibility = "visible";
    camFrame.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  }

  function closeOverlay() {
    overlayDoneType = null;
    camOverlay.classList.remove("open");
    camOverlay.hidden = true;
    camFrame.src = "about:blank";
  }

  window.addEventListener("message", (ev) => {
    const data = ev && ev.data;
    if (data && data.type === overlayDoneType) {
      closeOverlay();
    }
  });

  overlayClose.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeOverlay();
  });

  btnTabletSetup.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Opens straight to the General tab (camera/charge-LED/rotation); Home
    // Assistant/Wi-Fi/MQTT/Cameras are all one click away from there. This
    // health check only needs to cover setup-wizard.py itself — General's
    // own toggles always work via power-api regardless of whether the
    // camera stream service happens to be running.
    openOverlay(setupUrl(), "ha-kiosk-setup-done", SETUP_BASE);
  });

  function fmtUptime(sec) {
    if (sec == null) return "—";
    const s = Math.floor(sec);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderInfo(data) {
    const wifi = data.wifi || {};
    const up = data.uptime || {};
    const ha = data.ha || {};
    const power = data.power || {};
    const thermal = data.thermal || {};
    const display = data.display || {};
    const disk = data.disk || {};
    const mem = up.memory || {};

    haPill.textContent = ha.ok ? "HA ok" : "HA down";
    haPill.className = `pill ${ha.ok ? "ok" : "bad"}`;

    const batt = power.battery_percent != null ? `${power.battery_percent}%` : "—";
    const pct = power.battery_percent;
    const isDischarging = String(power.battery_status || "").toLowerCase() === "discharging";
    // "Plugged In" alone doesn't mean the battery is actually gaining charge
    // — confirmed on this hardware that an inadequate charger/cable can
    // leave it discharging the whole time it's "plugged in", which is
    // exactly what led to an unclean-shutdown scare. Surface that plainly
    // instead of it only being discoverable by SSHing in mid-crisis.
    const chargerInadequate = power.plugged_in && isDischarging;
    const powerTxt = chargerInadequate
      ? `Batt ${batt} — charger inadequate!`
      : power.charging
        ? `Batt ${batt} charging`
        : power.plugged_in
          ? `Batt ${batt} AC`
          : `Batt ${batt}`;
    let powerCls = "";
    if (chargerInadequate || (pct != null && pct <= 5 && isDischarging)) {
      powerCls = "bad";
    } else if (pct != null && pct <= 20 && isDischarging) {
      powerCls = "warn"; // matches kiosk-guardian.py's auto-dim threshold
    }
    const wifiTxt = [
      wifi.ssid || "Wi‑Fi",
      wifi.signal != null ? `${wifi.signal}%` : (wifi.level_dbm != null ? `${wifi.level_dbm} dBm` : null),
    ].filter(Boolean).join(" ");
    const temp = thermal.cpu_c != null ? `${thermal.cpu_c}°C` : (thermal.soc_c != null ? `${thermal.soc_c}°C` : null);
    const screenState = display.blanked ? "Screen blanked" : (display.state === "on" || display.state == null ? "Screen on" : `Screen ${display.state}`);
    const sysBits = [
      disk.used_percent != null ? `Disk ${disk.used_percent}%` : null,
      mem.used_pct != null ? `RAM ${mem.used_pct}%` : null,
    ].filter(Boolean);
    const chips = [
      wifi.ip ? { text: wifi.ip } : null,
      { text: powerTxt, cls: powerCls },
      { text: screenState },
      temp ? { text: `CPU ${temp}` } : null,
      { text: `Up ${fmtUptime(up.seconds)}` },
      sysBits.length ? { text: sysBits.join(" · ") } : null,
      data.rotation && data.rotation !== "normal" ? { text: data.rotation } : null,
    ].filter(Boolean);

    info.innerHTML = `
      <div class="primary">
        <span>${esc(wifiTxt)}</span>
        <span>${esc(data.hostname || "")}</span>
      </div>
      <div class="meta">${chips.map((c) => `<span class="chip${c.cls ? " " + c.cls : ""}">${esc(c.text)}</span>`).join("")}</div>
    `;
    if (data.brightness && data.brightness.supported && data.brightness.percent != null) {
      bright.value = String(data.brightness.percent);
      brightLabel.textContent = `${data.brightness.percent}%`;
    }
  }

  async function api(action, body) {
    const opts = {
      method: action === "status" ? "GET" : "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    };
    if (opts.method === "POST") opts.body = JSON.stringify(body || {});
    const path = action === "status" ? "/status" : `/${encodeURIComponent(action)}`;
    const res = await fetch(`${POWER_BASE}${path}`, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  async function refreshStatus() {
    try {
      const data = await api("status");
      renderInfo(data);
    } catch (err) {
      haPill.textContent = "API down";
      haPill.className = "pill bad";
      info.innerHTML = `<div class="meta">${esc(err.message || err)}</div>`;
    }
  }

  function setControlsEnabled(enabled) {
    buttons.forEach((b) => { b.disabled = !enabled; });
    bright.disabled = !enabled;
  }

  function setOpen(next) {
    open = next;
    panel.classList.toggle("open", open);
    backdrop.classList.toggle("open", open);
    tab.textContent = open ? "›" : "‹";
    tab.setAttribute("aria-label", open ? "Close tablet controls" : "Open tablet controls");
    tab.style.right = open ? PANEL_WIDTH : "0";
    if (open) {
      refreshStatus();
      statusTimer = setInterval(refreshStatus, 8000);
    } else {
      statusEl.textContent = "";
      if (statusTimer) clearInterval(statusTimer);
      statusTimer = null;
    }
  }

  tab.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen(!open);
  });
  backdrop.addEventListener("click", () => setOpen(false));

  async function runAction(btn) {
    if (busy) return;
    const action = btn.getAttribute("data-action");
    if (!action) return;
    const confirmMsg = btn.getAttribute("data-confirm");
    if (confirmMsg && !window.confirm(confirmMsg)) return;

    const body = {};
    if (btn.hasAttribute("data-delta")) body.delta = Number(btn.getAttribute("data-delta"));
    if (btn.hasAttribute("data-direction")) body.direction = btn.getAttribute("data-direction");
    if (btn.hasAttribute("data-percent")) body.percent = Number(btn.getAttribute("data-percent"));

    busy = true;
    setControlsEnabled(false);
    statusEl.textContent = "Working…";
    try {
      const data = await api(action, body);
      statusEl.textContent = data.message || "Done";
      if (data.brightness && data.brightness.percent != null) {
        bright.value = String(data.brightness.percent);
        brightLabel.textContent = `${data.brightness.percent}%`;
      }
      if (action === "rotate" && data.rotation && window.__haKioskApplyRotation) {
        window.__haKioskApplyRotation(data.rotation);
      }
      await refreshStatus();
      if (["reboot", "shutdown", "chromium-restart", "clear-cache"].includes(action)) return;
    } catch (err) {
      statusEl.textContent = String(err && err.message ? err.message : err);
    }
    busy = false;
    setControlsEnabled(true);
  }

  buttons.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      runAction(btn);
    });
  });

  let brightTimer = null;
  bright.addEventListener("input", () => {
    brightLabel.textContent = `${bright.value}%`;
  });
  bright.addEventListener("change", () => {
    if (brightTimer) clearTimeout(brightTimer);
    brightTimer = setTimeout(async () => {
      try {
        await api("brightness", { percent: Number(bright.value) });
        statusEl.textContent = `Brightness ${bright.value}%`;
      } catch (err) {
        statusEl.textContent = String(err.message || err);
      }
    }, 80);
  });

  // Update-available bubble on the closed tab. Reads the cache
  // self-update.py's check/os-check write to (fed by both the daily 06:00
  // timer and a manual "Check for updates" tap in Setup > Updates) —
  // cheap, no GitHub/apt call of its own, so this can poll often.
  async function pollUpdateAvailable() {
    try {
      const res = await fetch(POWER_BASE + "/update-available", { cache: "no-store" });
      const data = await res.json();
      const kioskAvail = !!(data.kiosk && data.kiosk.update_available);
      const osAvail = !!(data.os && data.os.update_available);
      updateAvailable = kioskAvail || osAvail;
      tab.classList.toggle("has-update", updateAvailable);
    } catch (_) {
      // Leave the last known state — a transient fetch failure shouldn't
      // flicker the badge off.
    }
  }
  pollUpdateAvailable();
  setInterval(pollUpdateAvailable, 5 * 60 * 1000);

})();
