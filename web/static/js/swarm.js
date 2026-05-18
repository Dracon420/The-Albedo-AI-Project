// ============================================================
// swarm.js — poll eel.get_swarm_status() and update the 3 LED dots.
//
// The dots are styled via [data-state] in CSS:
//   standby = orange, active = cyan, error = red
// ============================================================

const Swarm = (() => {
  const POLL_MS = 750;
  let _timer = null;

  function _apply(state) {
    if (!state) return;
    for (const agent of Object.keys(state)) {
      const dot = document.querySelector(
        `.swarm__pill[data-agent="${agent}"] .swarm__dot`);
      if (dot) dot.setAttribute("data-state", state[agent] || "standby");
    }
  }

  async function _tick() {
    try {
      const r = await eel.get_swarm_status()();
      if (r && r.ok) _apply(r.data);
    } catch (err) {
      console.warn("[swarm] poll error:", err);
    }
  }

  function start() {
    if (_timer) return;
    _tick();
    _timer = setInterval(_tick, POLL_MS);
  }

  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  return { start, stop, apply: _apply };
})();

window.Swarm = Swarm;
