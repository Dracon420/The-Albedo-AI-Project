/**
 * api_keys_panel.js — manage provider API keys from Settings.
 *
 * Mounts into any container. Lists every key Albedo knows about with a
 * masked-by-default field, SET/NOT-SET status, a [?] link to the provider's
 * key page, SHOW/HIDE toggle, and a single SAVE that batches updates.
 *
 * Backend: get_api_keys_status / set_api_keys (writes .env, hot-reloads
 * providers so the new keys are picked up immediately).
 *
 * Usage: ApiKeysPanel.mount(rootEl)
 */
(function () {
  "use strict";

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("panel", "panel--api-keys");

    root.appendChild(_el("div", "panel__title", "⌬ API KEYS"));
    const status = _el("div", "panel__status", "loading…");
    root.appendChild(status);

    let info;
    try { info = await eel.get_api_keys_status()(); }
    catch (e) { status.textContent = "bridge error: " + e; return; }
    if (!info || !info.ok) { status.textContent = "error: " + (info && info.error); return; }

    const inputs = {};   // env_key -> <input>

    info.items.forEach((item) => {
      const field = _el("div", "panel__field");
      const lblRow = _el("div", "panel__keyrow-head");
      lblRow.appendChild(_el("span", "panel__label", item.label));
      const badge = _el("span",
        "panel__key-badge " + (item.set ? "panel__key-badge--set" : "panel__key-badge--unset"),
        item.set ? `SET${item.preview ? "  " + item.preview : ""}` : "not set");
      lblRow.appendChild(badge);
      const helpLink = document.createElement("a");
      helpLink.href = item.url; helpLink.target = "_blank";
      helpLink.className = "panel__keylink"; helpLink.textContent = "[get key ▸]";
      lblRow.appendChild(helpLink);
      field.appendChild(lblRow);

      const row = _el("div", "panel__keyrow");
      const inp = document.createElement("input");
      inp.type = "password";
      inp.className = "panel__input panel__keyinput";
      inp.placeholder = item.set
        ? "(leave blank to keep existing — type to replace, or 'CLEAR' to remove)"
        : "paste key here";
      inp.dataset.envkey = item.key;
      const showBtn = _el("button", "cmd-btn panel__keyshow", "SHOW");
      showBtn.addEventListener("click", () => {
        const visible = inp.type === "text";
        inp.type = visible ? "password" : "text";
        showBtn.textContent = visible ? "SHOW" : "HIDE";
      });
      row.appendChild(inp);
      row.appendChild(showBtn);
      field.appendChild(row);
      root.appendChild(field);
      inputs[item.key] = inp;
    });

    const saveBtn = _el("button", "cmd-btn cmd-btn--accent panel__save", "SAVE KEYS");
    root.appendChild(saveBtn);
    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      const updates = {};
      Object.entries(inputs).forEach(([key, inp]) => {
        const v = inp.value;
        if (v === "") return;                 // unchanged
        if (v.trim().toUpperCase() === "CLEAR") updates[key] = "";   // remove
        else                                    updates[key] = v.trim();
      });
      if (!Object.keys(updates).length) {
        status.textContent = "(no changes)";
        saveBtn.disabled = false;
        return;
      }
      try {
        const r = await eel.set_api_keys(updates)();
        if (r && r.ok) {
          status.textContent = `saved ${r.updated.length} key(s) — providers reloaded.`;
          // Re-render so SET/NOT-SET status updates
          setTimeout(() => mount(root), 800);
        } else {
          status.textContent = "save error: " + (r && r.error);
        }
      } catch (e) {
        status.textContent = "save failed: " + e;
      } finally {
        saveBtn.disabled = false;
      }
    });

    const setCount = info.items.filter((i) => i.set).length;
    status.textContent = `${setCount} / ${info.items.length} keys configured`;
  }

  window.ApiKeysPanel = { mount };
})();
