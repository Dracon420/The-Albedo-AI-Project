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

    // ── Card grid ──
    const grid = _el("div", "team-grid");
    const cards = {};
    ROLES.forEach((role) => {
      const card = _el("div", "team-card", null);
      card.dataset.role = role;
      card.dataset.state = "idle";
      const head = _el("div", "team-card__head");
      const dot  = _el("span", "team-card__dot");
      head.appendChild(dot);
      head.appendChild(_el("span", "team-card__role", role));
      card.appendChild(head);
      card.appendChild(_el("div", "team-card__state", "idle"));
      card.appendChild(_el("div", "team-card__task", "—"));
      card.appendChild(_el("div", "team-card__tool", ""));
      grid.appendChild(card);
      cards[role] = card;
    });
    root.appendChild(grid);

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
