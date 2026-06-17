/**
 * team_roles_panel.js — assign a brain (provider) to each team specialist.
 *
 * Mounts into any container. For each of the 10 specialists, a dropdown lets
 * you pick which provider it uses (Anthropic / OpenAI / Azure / Gemini / Groq /
 * Ollama / global). "Global" means use the system-wide Reasoning Core setting.
 *
 * Backend: get_team_roles / set_team_roles (persists agent_roles in settings.json).
 *
 * Usage: TeamRolesPanel.mount(rootEl)
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
    root.classList.add("panel", "panel--team-roles");

    root.appendChild(_el("div", "panel__title", "◆ AGENT BRAINS (per role)"));
    const status = _el("div", "panel__status", "loading…");
    root.appendChild(status);

    let info;
    try { info = await eel.get_team_roles()(); }
    catch (e) { status.textContent = "bridge error: " + e; return; }
    if (!info || !info.ok) { status.textContent = "error: " + (info && info.error); return; }

    const providers = Object.keys(info.available || {});
    const selects = {};   // role -> <select>

    Object.entries(info.roles || {}).forEach(([role, meta]) => {
      const field = _el("div", "panel__field");
      const head = _el("div", "panel__keyrow-head");
      head.appendChild(_el("span", "panel__label", role));
      head.appendChild(_el("span", "panel__role-tools",
        "tools: " + ((meta.tools && meta.tools.length) ? meta.tools.join(", ") : "(no tools)")));
      field.appendChild(head);

      const sel = _el("select", "panel__select");
      const auto = _el("option", null, "(use global Reasoning Core)");
      auto.value = "";
      sel.appendChild(auto);
      providers.forEach((p) => {
        const ready = info.available[p];
        const o = _el("option", null, p + (ready ? "" : "  — no key"));
        o.value = p;
        if (!ready) o.disabled = true;
        if (meta.provider === p) o.selected = true;
        sel.appendChild(o);
      });
      field.appendChild(sel);
      root.appendChild(field);
      selects[role] = sel;
    });

    const saveBtn = _el("button", "cmd-btn cmd-btn--accent panel__save", "SAVE ROLES");
    root.appendChild(saveBtn);
    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      const mapping = {};
      Object.entries(selects).forEach(([role, sel]) => {
        // Always include — empty string means "use global", which we want to persist
        if (sel.value) mapping[role] = sel.value;
      });
      try {
        const r = await eel.set_team_roles(mapping)();
        status.textContent = r && r.ok
          ? `saved — ${Object.keys(r.agent_roles || {}).length} role(s) mapped explicitly.`
          : "save error: " + (r && r.error || "unknown");
      } catch (e) {
        status.textContent = "save failed: " + e;
      } finally {
        saveBtn.disabled = false;
      }
    });

    status.textContent = `${Object.keys(info.roles || {}).length} specialists`;
  }

  window.TeamRolesPanel = { mount };
})();
