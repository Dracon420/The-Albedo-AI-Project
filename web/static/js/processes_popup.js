/**
 * processes_popup.js — running-process chooser modal.
 *
 * Opens automatically the first time the agent runs list_top_processes (via the
 * event bus), or on demand via window._albedo_show_processes(). Lists processes
 * largest-RAM first with checkboxes; selected ones can be stopped after a
 * confirm. Critical OS/Albedo processes are shown but not selectable.
 *
 * Mirrors apps_popup.js and reuses its .apps-modal styles.
 */
(function () {
  "use strict";

  let _modal = null, _listEl = null;
  // Once dismissed, don't auto-re-pop on later list_top_processes calls.
  let _userClosed = false;

  function _ensure() {
    if (_modal) return;
    _modal = document.createElement("div");
    _modal.className = "apps-modal procs-modal";
    _modal.innerHTML = `
      <div class="apps-modal__box">
        <div class="apps-modal__head">
          <span>RUNNING PROCESSES &mdash; highest RAM first</span>
          <button class="apps-modal__x" title="Close">&times;</button>
        </div>
        <div class="apps-modal__hint">
          Tick processes to stop, then STOP. Critical system &amp; Albedo
          processes are locked &mdash; stopping the wrong app loses unsaved work.
        </div>
        <div class="apps-modal__list"></div>
        <div class="apps-modal__foot">
          <button class="cmd-btn apps-modal__kill">STOP SELECTED</button>
          <button class="cmd-btn apps-modal__close">CLOSE</button>
        </div>
      </div>`;
    document.body.appendChild(_modal);
    _listEl = _modal.querySelector(".apps-modal__list");
    _modal.querySelector(".apps-modal__x").onclick = close;
    _modal.querySelector(".apps-modal__close").onclick = close;
    _modal.querySelector(".apps-modal__kill").onclick = _kill;
    _modal.addEventListener("click", (e) => { if (e.target === _modal) close(); });
  }

  function close() { if (_modal) _modal.classList.remove("is-open"); _userClosed = true; }
  function autoOpen() { if (!_userClosed) open(); }

  function _esc(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  async function open() {
    _ensure();
    _listEl.innerHTML = "<div class='apps-modal__loading'>Reading running processes…</div>";
    _modal.classList.add("is-open");
    try {
      const r = await eel.get_process_list(25)();
      if (!r || !r.ok || !Array.isArray(r.data) || !r.data.length) {
        _listEl.innerHTML = "<div class='apps-modal__loading'>No processes found.</div>";
        return;
      }
      _listEl.innerHTML = "";
      r.data.forEach((p) => {
        const meta = (p.count > 1 ? p.count + "× · " : "") + "CPU " + (p.cpu || 0) + "%";
        const row = document.createElement("label");
        row.className = "apps-row" + (p.critical ? " apps-row--locked" : "");
        const box = p.critical
          ? `<input type="checkbox" disabled title="protected system process">`
          : `<input type="checkbox" value="${_esc(p.name)}">`;
        row.innerHTML =
          box +
          `<span class="apps-row__name">${_esc(p.name)}${p.critical ? " 🔒" : ""}</span>` +
          `<span class="apps-row__size">${p.ram_mb ? Math.round(p.ram_mb) + " MB" : "—"}</span>` +
          `<span class="apps-row__use">${_esc(meta)}</span>`;
        _listEl.appendChild(row);
      });
    } catch (e) {
      _listEl.innerHTML = "<div class='apps-modal__loading'>Error: " + _esc(e) + "</div>";
    }
  }

  async function _kill() {
    const checked = [..._listEl.querySelectorAll("input:checked")].map((c) => c.value);
    if (!checked.length) return;
    if (!window.confirm("Stop these " + checked.length + " process(es)?\n\n" + checked.join("\n"))) return;
    const btn = _modal.querySelector(".apps-modal__kill");
    btn.disabled = true; btn.textContent = "STOPPING…";
    try { await eel.kill_processes(checked)(); } catch (e) { /* ignore */ }
    btn.disabled = false; btn.textContent = "STOP SELECTED";
    open();   // refresh
  }

  // Explicit user request always opens (and re-arms auto-open).
  window._albedo_show_processes = function () { _userClosed = false; open(); };
  if (window.eel) { try { eel.expose(_albedo_show_processes, "_albedo_show_processes"); } catch (_) {} }

  // Auto-open the first time the agent lists processes; respects dismissal after.
  (function wire() {
    if (window.EventBus) {
      EventBus.on("tool.result", (e) => {
        if (e && e.name === "list_top_processes") autoOpen();
      });
    } else { setTimeout(wire, 300); }
  })();
})();
