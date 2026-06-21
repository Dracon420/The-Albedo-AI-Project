/**
 * team_viz.js — LIVE visualization of the specialist team.
 *
 * Renders one card per role (8 specialists), color-coded by current state:
 *   idle (gray) | thinking (cyan-pulse) | tool (amber-pulse) | done (green) | error (red)
 * Plus a chronological timeline of events: who did what, when.
 *
 * Subscribes to backend events via EventBus (see event_bus_client.js).
 *
 * Usage:
 *   TeamViz.mount(rootEl)
 */
(function () {
  "use strict";

  const ROLES = [
    "Orchestrator", "SysOps", "Researcher", "FileScout",
    "Code Writer", "Analyzer", "Designer", "Critic",
    "Math", "FactChecker",
  ];

  // Monochrome glyph per role (picks up cyberdeck glow via currentColor).
  const ROLE_GLYPH = {
    "Orchestrator": "◈", "SysOps": "⚙", "Researcher": "◎", "FileScout": "▣",
    "Code Writer": "⟨⟩", "Analyzer": "▤", "Designer": "◇", "Critic": "✓",
    "Math": "∑", "FactChecker": "⊜",
  };

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function _ts() {
    const d = new Date();
    return d.toLocaleTimeString([], { hour12: false });
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("viz", "viz--team");

    // ── Banner ──
    const banner = _el("div", "viz__banner", "Team idle.");
    root.appendChild(banner);

    // ── Live status summary strip (counts by state) ──
    const summary = _el("div", "team-summary");
    const SUM_STATES = ["thinking", "tool", "done", "error", "idle"];
    const sumEls = {};
    SUM_STATES.forEach((s) => {
      const chip = _el("span", `team-summary__chip team-summary__chip--${s}`);
      chip.appendChild(_el("span", "team-summary__dot"));
      const n = _el("span", "team-summary__n", "0");
      chip.appendChild(n);
      chip.appendChild(_el("span", "team-summary__lbl", s));
      summary.appendChild(chip);
      sumEls[s] = n;
    });
    root.appendChild(summary);

    function _buildCard(role, featured) {
      const card = _el("div", featured ? "team-card team-card--lead" : "team-card", null);
      card.dataset.role = role;
      card.dataset.state = "idle";
      const head = _el("div", "team-card__head");
      head.appendChild(_el("span", "team-card__glyph", ROLE_GLYPH[role] || "•"));
      head.appendChild(_el("span", "team-card__dot"));
      head.appendChild(_el("span", "team-card__role", role));
      card.appendChild(head);
      card.appendChild(_el("div", "team-card__state", "idle"));
      card.appendChild(_el("div", "team-card__task", "—"));
      card.appendChild(_el("div", "team-card__tool", ""));
      return card;
    }

    const cards = {};

    // ── Orchestrator featured as the team hub ──
    const lead = _buildCard("Orchestrator", true);
    cards["Orchestrator"] = lead;
    root.appendChild(lead);

    // ── Specialist card grid ──
    const grid = _el("div", "team-grid");
    ROLES.filter((r) => r !== "Orchestrator").forEach((role) => {
      const card = _buildCard(role, false);
      grid.appendChild(card);
      cards[role] = card;
    });
    root.appendChild(grid);

    function _refreshSummary() {
      const counts = { thinking: 0, tool: 0, done: 0, error: 0, idle: 0 };
      Object.values(cards).forEach((c) => {
        const s = c.dataset.state;
        if (counts[s] !== undefined) counts[s]++;
      });
      SUM_STATES.forEach((s) => { sumEls[s].textContent = counts[s]; });
    }
    _refreshSummary();

    // ── Timeline ──
    const tlWrap = _el("div", "viz__section");
    tlWrap.appendChild(_el("div", "viz__section-head", "Timeline"));
    const tl = _el("div", "team-timeline");
    tlWrap.appendChild(tl);
    root.appendChild(tlWrap);

    function setCardState(role, state, task, toolText) {
      const card = cards[role];
      if (!card) return;
      card.dataset.state = state;
      card.querySelector(".team-card__state").textContent = state;
      if (task !== undefined) card.querySelector(".team-card__task").textContent = task || "—";
      if (toolText !== undefined) card.querySelector(".team-card__tool").textContent = toolText || "";
      _refreshSummary();
    }

    function addTimeline(role, text, kind) {
      const row = _el("div", `team-tl__row team-tl__row--${kind || "info"}`);
      row.appendChild(_el("span", "team-tl__ts", _ts()));
      row.appendChild(_el("span", "team-tl__role", role || "—"));
      row.appendChild(_el("span", "team-tl__text", text));
      tl.insertBefore(row, tl.firstChild);
      // Keep the timeline bounded
      while (tl.childNodes.length > 200) tl.removeChild(tl.lastChild);
    }

    // ── Subscribe to backend events ──
    if (!window.EventBus) {
      banner.textContent = "EventBus client not loaded.";
      return;
    }
    EventBus.on("team.start", (e) => {
      banner.textContent = "Team working on: " + (e.goal || "");
      ROLES.forEach((r) => setCardState(r, "idle", "—", ""));
      addTimeline("team", "started: " + (e.goal || ""), "info");
    });
    EventBus.on("team.plan", (e) => {
      const n = (e.tasks || []).length;
      addTimeline("Orchestrator", `planned ${n} task(s)` + (e.revision ? " (revision)" : ""), "info");
      (e.tasks || []).forEach((t) => setCardState(t.role, "idle", t.task, ""));
    });
    EventBus.on("agent.state", (e) => {
      if (!ROLES.includes(e.role)) return;
      setCardState(e.role, e.state, e.task);
      if (e.state === "thinking") addTimeline(e.role, "thinking: " + (e.task || ""), "info");
      if (e.state === "done")     addTimeline(e.role, "done",  "ok");
      if (e.state === "error")    addTimeline(e.role, "error", "err");
    });
    EventBus.on("tool.call", (e) => {
      const args = JSON.stringify(e.args || {}).slice(0, 80);
      setCardState(e.role, "tool", undefined, `${e.name}(${args})`);
      addTimeline(e.role, `tool: ${e.name}`, "tool");
    });
    EventBus.on("tool.result", (e) => {
      addTimeline(e.role, `result: ${e.summary || ""}`, e.ok ? "ok" : "err");
    });
    EventBus.on("team.critique", (e) => {
      const verdict = e.complete ? "complete" : "incomplete";
      addTimeline("Critic", `${verdict} — ${e.summary || ""}`, e.complete ? "ok" : "err");
    });
    EventBus.on("team.done", (e) => {
      banner.textContent = e.ok ? "Team idle (last run: ok)." : "Team idle (last run: failed).";
      addTimeline("team", e.ok ? "team done" : "team failed", e.ok ? "ok" : "err");
    });
    EventBus.on("router.decision", (e) => {
      addTimeline("Router", `${e.mode}: ${e.reason || ""}`, "info");
    });

    // Replay any events that fired before the window opened.
    EventBus.replayHistory(200);
  }

  window.TeamViz = { mount };
})();
