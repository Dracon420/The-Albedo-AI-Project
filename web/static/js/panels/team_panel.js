/**
 * team_panel.js — TEAM surface: specialist roster + per-role provider + run goal.
 *
 * Host-agnostic: TeamPanel.mount(rootEl) renders into a drawer pane OR a
 * standalone team_window.html.
 *
 * Backend:
 *   get_team_roles()           -> {ok, roles:{name:{tools,provider}}, available}
 *   set_team_roles(mapping)    -> {ok, agent_roles}
 *   run_team_query(goal)       -> {ok, goal, plan, results, critique, error}
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
    root.classList.add("panel", "panel--team");

    root.appendChild(_el("div", "panel__title", "◆ TEAM — SPECIALIST AGENTS"));
    const status = _el("div", "panel__status", "loading roster…");
    root.appendChild(status);

    let info;
    try {
      info = await eel.get_team_roles()();
    } catch (e) {
      status.textContent = "bridge unavailable: " + e;
      return;
    }
    if (!info || !info.ok) {
      status.textContent = "error: " + (info && info.error || "unknown");
      return;
    }

    // ── Roster table ──
    const tableWrap = _el("div", "panel__roster");
    const header = _el("div", "panel__roster-row panel__roster-row--head");
    ["Role", "Tools", "Provider"].forEach((h) =>
      header.appendChild(_el("span", "panel__roster-cell", h))
    );
    tableWrap.appendChild(header);

    const providerOpts = Object.keys(info.available || {});
    const selects = {};   // role -> <select>

    Object.entries(info.roles || {}).forEach(([role, meta]) => {
      const row = _el("div", "panel__roster-row");
      row.appendChild(_el("span", "panel__roster-cell panel__roster-cell--role", role));
      const tools = (meta.tools && meta.tools.length)
        ? meta.tools.join(", ")
        : "(no tools — reasoning only)";
      row.appendChild(_el("span", "panel__roster-cell panel__roster-cell--tools", tools));

      const sel = _el("select", "panel__select panel__select--inline");
      const auto = _el("option", null, "(global / default)");
      auto.value = "";
      sel.appendChild(auto);
      providerOpts.forEach((p) => {
        const o = _el("option", null, p);
        o.value = p;
        if (meta.provider === p) o.selected = true;
        sel.appendChild(o);
      });
      const cell = _el("span", "panel__roster-cell");
      cell.appendChild(sel);
      row.appendChild(cell);

      tableWrap.appendChild(row);
      selects[role] = sel;
    });
    root.appendChild(tableWrap);

    const saveRolesBtn = _el("button", "cmd-btn panel__save", "SAVE ROLE PROVIDERS");
    root.appendChild(saveRolesBtn);
    saveRolesBtn.addEventListener("click", async () => {
      saveRolesBtn.disabled = true;
      const mapping = {};
      Object.entries(selects).forEach(([role, sel]) => {
        if (sel.value) mapping[role] = sel.value;
      });
      try {
        const r = await eel.set_team_roles(mapping)();
        status.textContent = r && r.ok
          ? `saved roles: ${Object.keys(r.agent_roles || {}).join(", ") || "(cleared)"}`
          : "save error: " + (r && r.error || "unknown");
      } catch (e) {
        status.textContent = "save failed: " + e;
      } finally {
        saveRolesBtn.disabled = false;
      }
    });

    // ── Goal box + run ──
    root.appendChild(_el("div", "panel__divider"));
    const goalWrap = _el("label", "panel__field");
    goalWrap.appendChild(_el("span", "panel__label", "Team Goal"));
    const goalInput = _el("textarea", "panel__input panel__input--multi");
    goalInput.rows = 3;
    goalInput.placeholder = "e.g. Report my top memory hog and whether C: is over 85% full.";
    goalWrap.appendChild(goalInput);
    root.appendChild(goalWrap);

    const runBtn = _el("button", "cmd-btn cmd-btn--accent panel__run", "RUN TEAM");
    root.appendChild(runBtn);

    const out = _el("pre", "panel__output");
    out.textContent = "(no run yet)";
    root.appendChild(out);

    runBtn.addEventListener("click", async () => {
      const goal = goalInput.value.trim();
      if (!goal) { out.textContent = "(empty goal)"; return; }
      runBtn.disabled = true;
      out.textContent = "[running…] this may take a minute or two while specialists work + you approve their plan/tools.";
      try {
        const r = await eel.run_team_query(goal)();
        if (!r || !r.ok) {
          out.textContent = "ERROR: " + (r && r.error || "unknown");
          return;
        }
        const lines = [`GOAL: ${r.goal}`, "", "--- PLAN ---"];
        (r.plan || []).forEach((t) => lines.push(`  [${t.role}] ${t.task}`));
        lines.push("", "--- RESULTS ---");
        (r.results || []).forEach((res) => {
          lines.push(`  [${res.role}] -> ${(res.answer || "").slice(0, 240)}`);
        });
        lines.push("", "--- CRITIQUE ---");
        const c = r.critique || {};
        lines.push(`  ${c.complete ? "✓ complete" : "✗ incomplete"} — ${c.summary || ""}`);
        if (c.gaps && c.gaps.length) {
          lines.push("  gaps:");
          c.gaps.forEach((g) => lines.push(`    - ${g}`));
        }
        if (r.revised) lines.push("  (one revision round was run to close gaps)");
        out.textContent = lines.join("\n");
      } catch (e) {
        out.textContent = "EXCEPTION: " + e;
      } finally {
        runBtn.disabled = false;
      }
    });

    status.textContent = `${Object.keys(info.roles || {}).length} specialists ready.`;
  }

  window.TeamPanel = { mount };
})();
