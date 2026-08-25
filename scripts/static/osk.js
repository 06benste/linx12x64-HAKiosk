// Lightweight on-screen keyboard for touchscreen text entry (this tablet has
// no physical keyboard). Self-contained, no dependencies. Shows itself only
// while a text field on this page is focused, and hides on request.
//
// chromium-extension/osk.js is the same keyboard adapted to run as a content
// script against the live Home Assistant dashboard (a separate origin, so it
// can't share this file directly) — keep the two in sync when changing key
// layouts or behavior.
(() => {
  if (window.__haKioskOsk) return;
  window.__haKioskOsk = true;

  const LOCALE_KEY = "haKioskOskLocale";

  const LETTERS = [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
    ["z", "x", "c", "v", "b", "n", "m"],
  ];

  // The meaningful US/UK difference for a software popup keyboard isn't
  // physical key position (there's no physical key to reposition) — it's
  // which currency symbol and quote/at ordering matches what people expect
  // from muscle memory. That's what this toggle changes.
  const SYMBOLS = {
    us: {
      sym1: [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["-", "/", ":", ";", "(", ")", "$", "&", "@", "\""],
        [".", ",", "?", "!", "'"],
      ],
      sym2: [
        ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="],
        ["_", "\\", "|", "~", "<", ">", "€", "£", "¥"],
        [".", ",", "?", "!", "'"],
      ],
    },
    uk: {
      sym1: [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["-", "/", ":", ";", "(", ")", "£", "&", "@", "\""],
        [".", ",", "?", "!", "'"],
      ],
      sym2: [
        ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="],
        ["_", "\\", "|", "~", "<", ">", "€", "$", "¥"],
        [".", ",", "?", "!", "'"],
      ],
    },
  };

  function isTextField(el) {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return !el.disabled && !el.readOnly;
    if (tag !== "input") return false;
    const type = (el.type || "text").toLowerCase();
    return (
      ["text", "password", "url", "search", "tel", "email", "number"].includes(type) &&
      !el.disabled &&
      !el.readOnly
    );
  }

  function setNativeValue(el, value) {
    const proto = el.tagName.toLowerCase() === "textarea" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insertAtCursor(el, text) {
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const next = el.value.slice(0, start) + text + el.value.slice(end);
    setNativeValue(el, next);
    const pos = start + text.length;
    el.setSelectionRange(pos, pos);
  }

  function backspaceAtCursor(el) {
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    if (start === end) {
      if (start === 0) return;
      const next = el.value.slice(0, start - 1) + el.value.slice(end);
      setNativeValue(el, next);
      el.setSelectionRange(start - 1, start - 1);
    } else {
      const next = el.value.slice(0, start) + el.value.slice(end);
      setNativeValue(el, next);
      el.setSelectionRange(start, start);
    }
  }

  let locale = "uk";
  try {
    locale = localStorage.getItem(LOCALE_KEY) === "us" ? "us" : "uk";
  } catch (_) { /* ignore */ }

  let target = null;
  let shift = false;
  let page = "letters"; // "letters" | "sym1" | "sym2"

  const root = document.createElement("div");
  root.id = "ha-kiosk-osk";
  document.documentElement.appendChild(root);

  const style = document.createElement("style");
  style.textContent = `
    #ha-kiosk-osk {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 999999;
      background: #171b21;
      border-top: 1px solid rgba(255,255,255,0.1);
      box-shadow: 0 -8px 24px rgba(0,0,0,0.4);
      padding: 12px 14px calc(12px + env(safe-area-inset-bottom, 0px));
      font-family: system-ui, -apple-system, sans-serif;
      transform: translateY(100%);
      transition: transform 0.18s ease;
      display: none;
    }
    #ha-kiosk-osk.open { display: block; transform: translateY(0); }
    #ha-kiosk-osk .osk-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 2px 12px;
      gap: 8px;
    }
    #ha-kiosk-osk .osk-locale {
      appearance: none;
      border: 1px solid rgba(255,255,255,0.14);
      background: #10141a;
      color: #9aa3ad;
      border-radius: 999px;
      font-size: 15px;
      font-weight: 700;
      padding: 8px 18px;
      min-height: 40px;
    }
    #ha-kiosk-osk .osk-hide {
      appearance: none;
      border: 0;
      background: transparent;
      color: #9aa3ad;
      font-size: 15px;
      font-weight: 650;
      padding: 8px 12px;
      min-height: 40px;
    }
    #ha-kiosk-osk .osk-row {
      display: flex;
      gap: 8px;
      margin-bottom: 8px;
      justify-content: center;
    }
    #ha-kiosk-osk .osk-key {
      appearance: none;
      border: 0;
      border-radius: 10px;
      background: #262c35;
      color: #eef1f4;
      font-size: 26px;
      min-height: 68px;
      flex: 1 1 0;
      max-width: 120px;
      cursor: pointer;
    }
    #ha-kiosk-osk .osk-key:active { background: #343e4a; }
    #ha-kiosk-osk .osk-key.wide { max-width: 170px; flex: 1.7 1 0; font-size: 17px; font-weight: 650; }
    #ha-kiosk-osk .osk-key.space { flex: 6 1 0; max-width: none; }
    #ha-kiosk-osk .osk-key.active { background: #2f6fed; }
    #ha-kiosk-osk .osk-key.enter { background: #2f6fed; max-width: 150px; }
  `;
  document.head.appendChild(style);

  function currentSymbolRows() {
    return SYMBOLS[locale][page];
  }

  function keyLabel(ch) {
    return page === "letters" && shift ? ch.toUpperCase() : ch;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function charKey(ch) {
    const label = keyLabel(ch);
    return `<button type="button" class="osk-key" data-char="${esc(label)}">${esc(label)}</button>`;
  }

  function render() {
    const rows = page === "letters" ? LETTERS : currentSymbolRows();
    const row3Left =
      page === "letters"
        ? `<button type="button" class="osk-key wide${shift ? " active" : ""}" data-action="shift">Shift</button>`
        : page === "sym1"
          ? `<button type="button" class="osk-key wide" data-action="sym2">#+=</button>`
          : `<button type="button" class="osk-key wide" data-action="sym1">123</button>`;
    const bottomLeftLabel = page === "letters" ? "123" : "ABC";
    const bottomLeftAction = page === "letters" ? "sym1" : "letters";

    root.innerHTML = `
      <div class="osk-topbar">
        <button type="button" class="osk-locale" data-action="locale">${locale.toUpperCase()}</button>
        <button type="button" class="osk-hide" data-action="hide">Hide keyboard</button>
      </div>
      <div class="osk-row">
        ${rows[0].map(charKey).join("")}
      </div>
      <div class="osk-row">
        ${rows[1].map(charKey).join("")}
      </div>
      <div class="osk-row">
        ${row3Left}
        ${rows[2].map(charKey).join("")}
        <button type="button" class="osk-key wide" data-action="backspace">Delete</button>
      </div>
      <div class="osk-row">
        <button type="button" class="osk-key wide" data-action="${bottomLeftAction}">${bottomLeftLabel}</button>
        <button type="button" class="osk-key space" data-char=" "> </button>
        <button type="button" class="osk-key enter" data-action="enter">enter</button>
      </div>
    `;
  }

  function open(el) {
    target = el;
    render();
    root.classList.add("open");
    document.body.style.paddingBottom = "230px";
    setTimeout(() => {
      if (target === el) el.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 200);
  }

  function close() {
    target = null;
    shift = false;
    page = "letters";
    root.classList.remove("open");
    document.body.style.paddingBottom = "";
  }

  // Prevent the field from ever losing focus when a key is tapped — the
  // standard trick for on-screen keyboards, so we don't need a fragile
  // focusout-with-delay dance to tell "tapped a key" from "tapped away".
  root.addEventListener("mousedown", (e) => e.preventDefault());

  root.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn || !target) return;
    const ch = btn.getAttribute("data-char");
    if (ch !== null) {
      insertAtCursor(target, ch);
      target.focus();
      return;
    }
    const action = btn.getAttribute("data-action");
    switch (action) {
      case "shift":
        shift = !shift;
        render();
        break;
      case "sym1":
        page = "sym1";
        render();
        break;
      case "sym2":
        page = "sym2";
        render();
        break;
      case "letters":
        page = "letters";
        render();
        break;
      case "backspace":
        backspaceAtCursor(target);
        target.focus();
        break;
      case "locale":
        locale = locale === "us" ? "uk" : "us";
        try {
          localStorage.setItem(LOCALE_KEY, locale);
        } catch (_) { /* ignore */ }
        render();
        break;
      case "enter":
        target.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
        close();
        break;
      case "hide":
        close();
        break;
    }
  });

  document.addEventListener("focusin", (e) => {
    if (isTextField(e.target)) open(e.target);
  });

  document.addEventListener("focusout", (e) => {
    // Only closes for a real focus loss (tapping elsewhere on the page) —
    // taps on the keyboard itself never blur the field in the first place
    // because of the mousedown preventDefault above. If a focusin for a
    // different field already fired (it fires synchronously, before this
    // timeout runs), target has moved on and this stale close() must not
    // undo it — so re-check against the specific element this event was
    // about, not just "is some text field focused right now".
    if (e.target !== target) return;
    const el = e.target;
    setTimeout(() => {
      if (target === el) close();
    }, 0);
  });
})();
