// ============================================================
// app.js — top-level controller. Wires modules together once the
//          DOM has loaded and the Eel websocket is ready.
// ============================================================

(function () {
  function start() {
    Drawer.init();
    Settings.init();
    Chat.init();
    Telemetry.start();
    Swarm.start();
    Neural.init();

    // Friendly banner once we know Eel is alive.
    eel.get_version()().then((r) => {
      if (r && r.ok) {
        // Apply persona from version payload (seeded from settings.json)
        if (r.persona && window._albedo_persona_push) {
          window._albedo_persona_push(r.persona);
        }
        const persona = r.persona || "ALBEDO";
        Chat.appendLine("system",
          `[SYS] Eel UI online — ${persona} v${r.version}, uptime ${r.uptime_s}s.`);
      }
    }).catch(() => {
      Chat.appendLine("error", "[SYS] Eel bridge unreachable.");
    });
  }

  // Eel exposes window.eel after /eel.js loads. Wait for DOMContentLoaded
  // OR a short poll for eel.js to be ready, whichever comes last.
  function _whenEelReady(cb) {
    if (typeof eel !== "undefined" && eel.get_version) { cb(); return; }
    setTimeout(() => _whenEelReady(cb), 50);
  }

  document.addEventListener("DOMContentLoaded", () => _whenEelReady(start));
})();
