/**
 * popup_factory.js — one place to define Albedo popups.
 *
 * Instead of hand-writing a modal + event wiring per tool, register a spec:
 *
 *   AlbedoPopup.register({
 *     id: "reminders",
 *     title: "REMINDERS",
 *     hint: "Active reminders. They fire as Windows notifications.",
 *     trigger: "list_reminders",          // tool name that auto-opens it (optional)
 *     mode: "list",
 *     dataEndpoint: "get_reminders",       // eel fn -> {ok, data:[...]}
 *     columns: [
 *       { key: "text", label: "Reminder", grow: true },
 *       { key: "when_human", label: "When" },
 *     ],
 *     selectable: true,
 *     lockKey: "fired",                    // rows where row[lockKey] is truthy can't be selected
 *     footActions: [
 *       { label: "CANCEL SELECTED", endpoint: "cancel_reminders",
 *         confirm: (sel) => `Cancel ${sel.length} reminder(s)?` },
 *     ],
 *   });
 *
 * Form mode:
 *   AlbedoPopup.register({
 *     id: "profile", title: "ABOUT YOU", trigger: "open_user_profile", mode: "form",
 *     loadEndpoint: "get_user_profile", saveEndpoint: "save_user_profile",
 *     dataKey: "profile",                  // key in the load result holding the values
 *     fields: [ {key:"name", label:"Name", kind:"input", ph:"…"}, ... ],
 *   });
 *
 * Reuses the .apps-modal CSS. Each popup also exposes window._albedo_show_<id>().
 */
(function () {
  "use strict";

  function _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function _make(spec) {
    let modal = null, listEl = null, fieldEls = {}, userClosed = false;
    const sel = Object.assign({ mode: "list", dismissGuard: true, selectable: false }, spec);

    function ensure() {
      if (modal) return;
      modal = document.createElement("div");
      modal.className = "apps-modal popup-" + sel.id;
      const foot = (sel.mode === "form")
        ? `<button class="cmd-btn cmd-btn--accent popup-save">SAVE</button>`
        : (sel.footActions || []).map((a, i) =>
            `<button class="cmd-btn ${a.accent ? "cmd-btn--accent" : ""} popup-foot" data-i="${i}">${_esc(a.label)}</button>`).join("");
      modal.innerHTML = `
        <div class="apps-modal__box">
          <div class="apps-modal__head">
            <span>${_esc(sel.title)}</span>
            <button class="apps-modal__x" title="Close">&times;</button>
          </div>
          ${sel.hint ? `<div class="apps-modal__hint">${_esc(sel.hint)}</div>` : ""}
          <div class="apps-modal__list ${sel.mode === "form" ? "profile-grid" : ""}"></div>
          <div class="apps-modal__foot">
            ${foot}
            <button class="cmd-btn popup-close">CLOSE</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      listEl = modal.querySelector(".apps-modal__list");
      modal.querySelector(".apps-modal__x").onclick = close;
      modal.querySelector(".popup-close").onclick = close;
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      if (sel.mode === "form") {
        modal.querySelector(".popup-save").onclick = save;
      } else {
        modal.querySelectorAll(".popup-foot").forEach((b) => {
          b.onclick = () => footAction(sel.footActions[+b.dataset.i]);
        });
      }
    }

    function close() { if (modal) modal.classList.remove("is-open"); userClosed = true; }
    function autoOpen() { if (!userClosed) open(); }

    async function open() {
      ensure();
      modal.classList.add("is-open");
      if (sel.mode === "form") return loadForm();
      return loadList();
    }

    // ── list mode ──────────────────────────────────────────────
    async function loadList() {
      listEl.innerHTML = "<div class='apps-modal__loading'>Loading…</div>";
      let r;
      try { r = await eel[sel.dataEndpoint].apply(null, sel.dataArgs || [])(); }
      catch (e) { listEl.innerHTML = "<div class='apps-modal__loading'>Error: " + _esc(e) + "</div>"; return; }
      const rows = (r && r.ok && Array.isArray(r.data)) ? r.data : [];
      if (!rows.length) {
        listEl.innerHTML = "<div class='apps-modal__loading'>" + _esc(sel.emptyText || "Nothing to show.") + "</div>";
        return;
      }
      listEl.innerHTML = "";
      rows.forEach((row) => {
        const locked = sel.lockKey && row[sel.lockKey];
        const el = document.createElement("label");
        el.className = "apps-row" + (locked ? " apps-row--locked" : "");
        let html = "";
        if (sel.selectable) {
          html += locked
            ? `<input type="checkbox" disabled title="locked">`
            : `<input type="checkbox" value="${_esc(row[sel.valueKey || "name"])}">`;
        }
        (sel.columns || []).forEach((c, i) => {
          const v = c.fmt ? c.fmt(row[c.key], row) : row[c.key];
          const cls = i === 0 ? "apps-row__name" : (c.dim ? "apps-row__use" : "apps-row__size");
          html += `<span class="${cls}"${c.grow ? ' style="flex:1"' : ""}>${_esc(v)}</span>`;
        });
        el.innerHTML = html;
        listEl.appendChild(el);
      });
    }

    async function footAction(act) {
      const checked = [...listEl.querySelectorAll("input:checked")].map((c) => c.value);
      if (!checked.length) return;
      if (act.confirm && !window.confirm(act.confirm(checked))) return;
      const btn = modal.querySelector(".popup-foot");
      const orig = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = "WORKING…"; }
      try { await eel[act.endpoint](checked)(); } catch (e) { /* ignore */ }
      if (btn) { btn.disabled = false; btn.textContent = orig; }
      loadList();
    }

    // ── form mode ──────────────────────────────────────────────
    function buildForm() {
      listEl.innerHTML = (sel.fields || []).map((f) => {
        const ctrl = f.kind === "area"
          ? `<textarea class="profile-field" data-k="${f.key}" rows="2" placeholder="${_esc(f.ph || "")}"></textarea>`
          : `<input class="profile-field" data-k="${f.key}" type="text" placeholder="${_esc(f.ph || "")}">`;
        return `<label class="profile-row"><span class="profile-row__label">${_esc(f.label)}</span>${ctrl}</label>`;
      }).join("");
      fieldEls = {};
      listEl.querySelectorAll(".profile-field").forEach((el) => { fieldEls[el.dataset.k] = el; });
    }

    async function loadForm() {
      if (!Object.keys(fieldEls).length) buildForm();
      try {
        const r = await eel[sel.loadEndpoint]()();
        const data = (r && (sel.dataKey ? r[sel.dataKey] : r.data)) || {};
        Object.keys(fieldEls).forEach((k) => { fieldEls[k].value = data[k] || ""; });
      } catch (e) { /* leave blank */ }
      const first = sel.fields && sel.fields[0] && fieldEls[sel.fields[0].key];
      if (first) first.focus();
    }

    async function save() {
      const data = {};
      Object.keys(fieldEls).forEach((k) => { data[k] = fieldEls[k].value.trim(); });
      const btn = modal.querySelector(".popup-save");
      btn.disabled = true; btn.textContent = "SAVING…";
      try { await eel[sel.saveEndpoint](data)(); btn.textContent = "SAVED ✓"; }
      catch (e) { btn.textContent = "FAILED"; }
      setTimeout(() => { btn.disabled = false; btn.textContent = "SAVE"; close(); }, 700);
    }

    // ── triggers ───────────────────────────────────────────────
    window["_albedo_show_" + sel.id] = function () { userClosed = false; open(); };
    if (window.eel) { try { eel.expose(window["_albedo_show_" + sel.id], "_albedo_show_" + sel.id); } catch (_) {} }
    if (sel.trigger) {
      (function wire() {
        if (window.EventBus) {
          EventBus.on("tool.result", (e) => {
            if (e && e.name === sel.trigger) (sel.dismissGuard ? autoOpen() : open());
          });
        } else { setTimeout(wire, 300); }
      })();
    }

    return { open, close };
  }

  window.AlbedoPopup = { register: _make };
})();
