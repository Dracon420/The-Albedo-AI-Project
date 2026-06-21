/**
 * apps_popup.js — installed-apps chooser modal.
 *
 * Opens automatically when the agent runs list_installed_apps (via the event
 * bus), or on demand via window._albedo_show_apps(). Shows apps largest-first
 * with checkboxes; selected apps can be uninstalled after a confirm.
 */
(function () {
  "use strict";

  let _modal = null, _listEl = null;

  function _ensure() {
    if (_modal) return;
    _modal = document.createElement("div");
    _modal.className = "apps-modal";
    _modal.innerHTML = `
      <div class="apps-modal__box">
        <div class="apps-modal__head">
          <span>INSTALLED APPS &mdash; largest first</span>
          <button class="apps-modal__x" title="Close">&times;</button>
        </div>
        <div class="apps-modal__hint">
          Tick apps to remove, then UNINSTALL. "usage not tracked" does NOT mean
          unused &mdash; verify before removing anything.
        </div>
        <div class="apps-modal__list"></div>
        <div class="apps-modal__foot">
          <button class="cmd-btn apps-modal__uninstall">UNINSTALL SELECTED</button>
          <button class="cmd-btn apps-modal__close">CLOSE</button>
        </div>
      </div>`;
    document.body.appendChild(_modal);
    _listEl = _modal.querySelector(".apps-modal__list");
    _modal.querySelector(".apps-modal__x").onclick = close;
    _modal.querySelector(".apps-modal__close").onclick = close;
    _modal.querySelector(".apps-modal__uninstall").onclick = _uninstall;
    _modal.addEventListener("click", (e) => { if (e.target === _modal) close(); });
  }

  function close() { if (_modal) _modal.classList.remove("is-open"); }

  function _esc(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  async function open() {
    _ensure();
    _listEl.innerHTML = "<div class='apps-modal__loading'>Reading installed apps…</div>";
    _modal.classList.add("is-open");
    try {
      const r = await eel.get_app_inventory(25)();
      if (!r || !r.ok || !Array.isArray(r.data) || !r.data.length) {
        _listEl.innerHTML = "<div class='apps-modal__loading'>No apps found.</div>";
        return;
      }
      _listEl.innerHTML = "";
      r.data.forEach((a) => {
        const use = a.last_used ? ("used " + a.last_used)
          : (a.run_count ? (a.run_count + " launches") : "usage not tracked");
        const row = document.createElement("label");
        row.className = "apps-row";
        row.innerHTML =
          `<input type="checkbox" value="${_esc(a.name)}">` +
          `<span class="apps-row__name">${_esc(a.name)}</span>` +
          `<span class="apps-row__size">${a.size_mb ? Math.round(a.size_mb) + " MB" : "—"}</span>` +
          `<span class="apps-row__use">${_esc(use)}</span>`;
        _listEl.appendChild(row);
      });
    } catch (e) {
      _listEl.innerHTML = "<div class='apps-modal__loading'>Error: " + _esc(e) + "</div>";
    }
  }

  async function _uninstall() {
    const checked = [..._listEl.querySelectorAll("input:checked")].map((c) => c.value);
    if (!checked.length) return;
    if (!window.confirm("Uninstall these " + checked.length + " app(s)?\n\n" + checked.join("\n"))) return;
    const btn = _modal.querySelector(".apps-modal__uninstall");
    btn.disabled = true; btn.textContent = "UNINSTALLING…";
    try { await eel.uninstall_apps(checked)(); } catch (e) { /* ignore */ }
    btn.disabled = false; btn.textContent = "UNINSTALL SELECTED";
    open();   // refresh the list
  }

  window._albedo_show_apps = function () { open(); };
  if (window.eel) { try { eel.expose(_albedo_show_apps, "_albedo_show_apps"); } catch (_) {} }

  // Auto-open whenever the agent finishes a list_installed_apps tool call.
  (function wire() {
    if (window.EventBus) {
      EventBus.on("tool.result", (e) => {
        if (e && e.name === "list_installed_apps") open();
      });
    } else { setTimeout(wire, 300); }
  })();
})();
