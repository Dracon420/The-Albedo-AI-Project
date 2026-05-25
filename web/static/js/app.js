// ============================================================
// app.js — top-level controller. Wires modules together once the
//          DOM and Eel websocket are ready.
// ============================================================

(function () {
  // Minimal appendLine that works even before Chat.init() runs.
  // Used to surface init errors that would otherwise be invisible.
  function _emergencyLog(kind, text) {
    const feed = document.getElementById("chat");
    if (!feed) return;
    const line = document.createElement("div");
    line.className = `chat__line chat__line--${kind}`;
    line.textContent = text;
    feed.appendChild(line);
    feed.scrollTop = feed.scrollHeight;
  }

  function start() {
    // Wrap each module init individually — one failure won't kill the rest.
    try { Drawer.init(); } catch (e) {
      _emergencyLog("error", "[SYS] Drawer init error: " + e);
    }
    try { Settings.init(); } catch (e) {
      _emergencyLog("error", "[SYS] Settings init error: " + e);
    }
    try { Chat.init(); } catch (e) {
      _emergencyLog("error", "[SYS] Chat init error: " + e);
    }
    try { Telemetry.start(); } catch (e) {
      _emergencyLog("error", "[SYS] Telemetry init error: " + e);
    }
    try { Swarm.start(); } catch (e) { /* non-fatal */ }
    try { Neural.init(); } catch (e) { /* non-fatal */ }

    // Confirm Eel bridge is alive and show persona.
    eel.get_version()().then((r) => {
      if (r && r.ok) {
        if (r.persona && window._albedo_persona_push) {
          window._albedo_persona_push(r.persona);
        }
        const persona = r.persona || "ALBEDO";
        Chat.appendLine("system",
          `[SYS] Eel UI online -- ${persona} v${r.version}, uptime ${r.uptime_s}s.`);
      }
    }).catch((e) => {
      Chat.appendLine("error", "[SYS] Eel bridge unreachable: " + e);
    });
  }

  // Poll until eel.js has loaded and registered its functions.
  function _whenEelReady(cb) {
    if (typeof eel !== "undefined" && typeof eel.get_version === "function") {
      cb();
      return;
    }
    setTimeout(() => _whenEelReady(cb), 50);
  }

  document.addEventListener("DOMContentLoaded", () => _whenEelReady(start));
})();
