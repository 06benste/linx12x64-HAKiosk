// On-screen keyboard for text fields on the live Home Assistant dashboard
// (Assist chat, input_text cards, etc.) — this tablet has no physical
// keyboard. Runs isolated in a shadow root so HA's CSS can't affect it and
// it can't affect HA's CSS, same pattern as power-drawer.js.
//
// This is the same keyboard as scripts/static/osk.js (used by the setup
// wizard), ported to a content script because that file lives on a
// different origin (127.0.0.1:17825) and a content script can't load
// another origin's file — keep the two in sync when changing key layouts
// or behavior. Only plain <input>/<textarea> elements are wired up here
// (best-effort — HA's more exotic custom editors are out of scope).
(() => {
  if (window.__haKioskOsk) return;
  window.__haKioskOsk = true;

  const LOCALE_KEY = "haKioskOskLocale";

  const LETTERS = [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
    ["z", "x", "c", "v", "b", "n", "m"],
  ];

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

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  let locale = "uk";
  try {
    locale = localStorage.getItem(LOCALE_KEY) === "us" ? "us" : "uk";
  } catch (_) { /* ignore */ }

  let target = null;
  let shift = false;
  let page = "letters"; // "letters" | "sym1" | "sym2"

  const host = document.createElement("div");
  host.id = "ha-kiosk-osk-root";
  host.style.cssText = "all:initial;position:fixed;inset:auto 0 0 0;pointer-events:none;z-index:2147483647;";
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host, * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
      .osk {
        pointer-events: auto;
        background: #171b21;
        color: #eef1f4;
        border-top: 1px solid rgba(255,255,255,0.1);
        box-shadow: 0 -8px 24px rgba(0,0,0,0.4);
        padding: 8px 8px calc(8px + env(safe-area-inset-bottom, 0px));
        transform: translateY(100%);
        transition: transform 0.18s ease;
        display: none;
      }
      .osk.open { display: block; transform: translateY(0); }
      .osk-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 2px 2px 12px;
        gap: 8px;
      }
      .osk-locale {
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
      .osk-hide {
        appearance: none;
        border: 0;
        background: transparent;
        color: #9aa3ad;
        font-size: 15px;
        font-weight: 650;
        padding: 8px 12px;
        min-height: 40px;
      }
      .osk-row { display: flex; gap: 8px; margin-bottom: 8px; justify-content: center; }
      .osk-key {
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
      .osk-key:active { background: #343e4a; }
      .osk-key.wide { max-width: 170px; flex: 1.7 1 0; font-size: 17px; font-weight: 650; }
      .osk-key.space { flex: 6 1 0; max-width: none; }
      .osk-key.active { background: #2f6fed; }
      .osk-key.enter { background: #2f6fed; max-width: 150px; }
    </style>
    <div class="osk"></div>
  `;
  const osk = shadow.querySelector(".osk");

  function keyLabel(ch) {
    return page === "letters" && shift ? ch.toUpperCase() : ch;
  }

  function charKey(ch) {
    const label = keyLabel(ch);
    return `<button type="button" class="osk-key" data-char="${esc(label)}">${esc(label)}</button>`;
  }

  function currentSymbolRows() {
    return SYMBOLS[locale][page];
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

    osk.innerHTML = `
      <div class="osk-topbar">
        <button type="button" class="osk-locale" data-action="locale">${locale.toUpperCase()}</button>
        <button type="button" class="osk-hide" data-action="hide">Hide keyboard</button>
      </div>
      <div class="osk-row">${rows[0].map(charKey).join("")}</div>
      <div class="osk-row">${rows[1].map(charKey).join("")}</div>
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
    osk.classList.add("open");
    setTimeout(() => {
      if (target === el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 200);
  }

  function close() {
    target = null;
    shift = false;
    page = "letters";
    osk.classList.remove("open");
  }

  osk.addEventListener("mousedown", (e) => e.preventDefault());

  osk.addEventListener("click", (e) => {
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

  document.addEventListener(
    "focusin",
    (e) => {
      // composedPath()[0] is the true focused node even across (open)
      // shadow-DOM boundaries — HA's inputs live behind several levels of
      // it (ha-textfield -> mwc-textfield -> input) and e.target alone
      // would be retargeted to an outer host element instead.
      const real = e.composedPath ? e.composedPath()[0] : e.target;
      if (isTextField(real)) open(real);
    },
    true
  );

  document.addEventListener(
    "focusout",
    (e) => {
      const real = e.composedPath ? e.composedPath()[0] : e.target;
      if (real !== target) return;
      // If a focusin for a different field already fired (they fire
      // synchronously, before this timeout), target has moved on and this
      // stale close() must not undo it. document.activeElement isn't a
      // reliable way to detect that here — for a focus target that lives
      // behind (possibly several levels of) shadow DOM, it reports the
      // outer custom-element host, not the real focused node.
      setTimeout(() => {
        if (target === real) close();
      }, 0);
    },
    true
  );
})();
