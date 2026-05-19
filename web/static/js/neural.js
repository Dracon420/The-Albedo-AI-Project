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

  // Display order — left column then right column, matched to the CSS grid.
  const ORDER = [
    "GEMINI",   "GROQ",
    "TOGETHER", "OLLAMA",
    "VEC_DB",   "WEBHOOK",
    "STT",      "TTS",
    "WAKE",     // last cell intentionally left half-empty so WAKE sits alone
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
      if (dot)   dot.setAttribute("data-status", entry.status || "off");
      if (label) label.textContent = entry.label || "--";
      if (entry.detail) cell.title = `${name} — ${entry.detail}`;
    }
  }

  function _applyAppState(state) {
    if (!_stateEl) return;
    const s = (state || "STANDBY").toUpperCase();
    _stateEl.textContent = s;
    _stateEl.setAttribute("data-state", s);
  }

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
