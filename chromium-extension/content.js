(() => {
  const auth = window.HA_KIOSK_AUTH || {};
  const user = auth.user || "";
  const pass = auth.pass || "";
  if (!user || !pass) return;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function walk(node, visit) {
    if (!node) return;
    visit(node);
    if (node.shadowRoot) walk(node.shadowRoot, visit);
    const children = node.children || [];
    for (const child of children) walk(child, visit);
  }

  function findLoginInputs(root) {
    let userInput = null;
    let passInput = null;
    let submit = null;
    walk(root, (node) => {
      if (!node.tagName) return;
      const tag = node.tagName.toLowerCase();
      if (tag === "input") {
        const type = (node.type || "").toLowerCase();
        const name = (node.name || node.autocomplete || node.id || "").toLowerCase();
        if (type === "password" && !passInput) passInput = node;
        if (
          !userInput &&
          (type === "text" || type === "email" || type === "username" || type === "") &&
          (name.includes("user") || name.includes("email") || name.includes("name") || type === "email" || type === "text")
        ) {
          userInput = node;
        }
      }
      if ((tag === "button" || (tag === "input" && node.type === "submit") || tag === "mwc-button" || tag === "ha-progress-button") && !submit) {
        const text = (node.textContent || node.value || "").toLowerCase();
        if (text.includes("log") || text.includes("sign") || node.getAttribute("type") === "submit") {
          submit = node;
        }
      }
    });
    // Fallback: first non-password text-like input before password
    if (!userInput && passInput) {
      walk(root, (node) => {
        if (userInput || !node.tagName || node.tagName.toLowerCase() !== "input") return;
        const type = (node.type || "text").toLowerCase();
        if (type !== "password" && type !== "hidden" && type !== "submit") userInput = node;
      });
    }
    return { userInput, passInput, submit };
  }

  function setNativeValue(el, value) {
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  let attempts = 0;
  const maxAttempts = 60;

  async function tryLogin() {
    attempts += 1;
    // Already past login (dashboard shell present)
    if (document.querySelector("home-assistant") && !document.querySelector("ha-authorize") && location.pathname.indexOf("auth") === -1) {
      const ha = document.querySelector("home-assistant");
      if (ha && ha.shadowRoot) return true;
    }

    const { userInput, passInput, submit } = findLoginInputs(document);
    if (userInput && passInput) {
      setNativeValue(userInput, user);
      setNativeValue(passInput, pass);
      await sleep(200);
      if (submit) {
        submit.click();
      } else if (passInput.form) {
        passInput.form.requestSubmit ? passInput.form.requestSubmit() : passInput.form.submit();
      } else {
        passInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
      }
      return true;
    }
    return false;
  }

  async function loop() {
    while (attempts < maxAttempts) {
      try {
        if (await tryLogin()) return;
      } catch (_) { /* keep trying */ }
      await sleep(1000);
    }
  }

  loop();
})();
