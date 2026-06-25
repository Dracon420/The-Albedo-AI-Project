// ============================================================
// neural.js — populate + poll the neural-links status grid +
//             the big STANDBY/ACTIVE/etc. state indicator
//             under the Albedo logo.
//
// Backend feeds come from:
//   eel.get_neural_links()   {ok, data: {NAME: {status, label, detail}}}
//   eel.get_app_state()      {ok, state: "STANDBY" | "ACTIVE" | "ERROR" | ...}
// ============================================================

const Neural = (() => {
  const POLL_MS = 1500;

  // Display order — flex strip wraps across rows. Grouped: swarm LLMs →
  // reasoning brains → local runtime → tools → vector store → IO → audio →
  // wake → dream. Kept in sync with _detect_neural_links() in bridge.py.
  const ORDER = [
    "GEMINI",   "GROQ",     "AZURE",
    "ANTHROPIC", "OLLAMA",  "WOLFRAM",
    "TAVILY",   "VEC_DB",   "WEBHOOK",
    "STT",      "TTS",      "WAKE",
    "DREAM",
    "EMAIL",    "CALENDAR", "HOME_ASST", "MESSAGING",
  ];

  let _gridEl, _stateEl, _statusEl;
  let _timer = null;
  let _built = false;

  function _ensureCells(links) {
    if (_built) return;
    _gridEl.innerHTML = "";
    for (const name of ORDER) {
      const cell = document.createElement("div");
      cell.className = "link";
      cell.dataset.link = name;
      cell.innerHTML = `
        <span class="link__dot"   data-status="off"></span>
        <span class="link__name">${name}</span>
        <span class="link__label">--</span>
      `;
      cell.title = name;
      _gridEl.appendChild(cell);
    }
    _built = true;
  }

  function _applyLinks(data) {
    if (!data) return;
    _ensureCells(data);
    for (const name of ORDER) {
      const cell = _gridEl.querySelector(`.link[data-link="${name}"]`);
      if (!cell) continue;
      const entry = data[name] || { status: "off", label: "--", detail: "" };
      const dot   = cell.querySelector(".link__dot");
      const label = cell.querySelector(".link__label");
      const st    = entry.status || "off";
      if (dot)   dot.setAttribute("data-status", st);
      if (label) {
        // When a subsystem is actively working, the WORD changes too (not just
        // the dot): READY → ACTIVE (green), error → ERROR (red).
        label.textContent = st === "active" ? "ACTIVE"
                          : st === "error"  ? "ERROR"
                          : (entry.label || "--");
        label.setAttribute("data-status", st);
      }
      if (entry.detail) cell.title = `${name} — ${entry.detail}`;
    }
  }

  function _applyAppState(state) {
    if (!_stateEl) return;
    const s = (state || "STANDBY").toUpperCase();
    _stateEl.textContent = s;
    _stateEl.setAttribute("data-state", s);
  }

  // Immediate push from the backend so the orb flips to ACTIVE the instant a
  // query starts (instead of waiting up to a full poll interval).
  window._albedo_state_push = function (state) {
    if (!_stateEl) _stateEl = document.getElementById("appState");
    _applyAppState(state);
  };
  if (window.eel) { try { eel.expose(_albedo_state_push, "_albedo_state_push"); } catch (_) {} }

  async function _tick() {
    try {
      const [linksR, stateR] = await Promise.all([
        eel.get_neural_links()(),
        eel.get_app_state()(),
      ]);
      if (linksR && linksR.ok) {
        _applyLinks(linksR.data);
        if (_statusEl) _statusEl.textContent = "// SYNCED";
      } else if (_statusEl) {
        _statusEl.textContent = "// DRIFT";
      }
      if (stateR && stateR.ok) _applyAppState(stateR.state);
    } catch (err) {
      console.warn("[neural] poll error:", err);
      if (_statusEl) _statusEl.textContent = "// OFFLINE";
    }
  }

  function init() {
    _gridEl   = document.getElementById("linksGrid");
    _stateEl  = document.getElementById("appState");
    _statusEl = document.getElementById("linksStatus");
    if (!_gridEl) return;   // HTML missing — skip silently
    _tick();
    _timer = setInterval(_tick, POLL_MS);
  }

  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  return { init, stop };
})();

window.Neural = Neural;
