/**
 * snap.js — preset window-layout controls. Calls eel.snap_windows(preset) which
 * uses win32gui to position Albedo's Chrome --app= windows into a tidy preset.
 *
 * Presets: 'left-stack' | 'thirds' | 'focus-chat'.
 *
 * Usage: Snap.attach(rootEl)   — appends a toolbar of preset buttons into root.
 */
(function () {
  "use strict";

  const PRESETS = [
    ["left-stack",  "⊞ LEFT STACK",  "Chat left half, Brain top-right, Team bottom-right"],
    ["thirds",      "⊞ THIRDS",      "Chat / Brain / Team as three equal columns"],
    ["focus-chat",  "⊞ FOCUS CHAT",  "Chat ~60% left, Brain + Team stacked right"],
  ];

  function attach(root) {
    if (!root || typeof eel === "undefined") return;
    const bar = document.createElement("div");
    bar.className = "snap-bar";
    PRESETS.forEach(([preset, label, tip]) => {
      const b = document.createElement("button");
      b.className = "cmd-btn snap-bar__btn";
      b.textContent = label;
      b.title = tip;
      b.addEventListener("click", async () => {
        b.disabled = true;
        try { await eel.snap_windows(preset)(); } catch (_) { /* ignore */ }
        finally { b.disabled = false; }
      });
      bar.appendChild(b);
    });
    root.appendChild(bar);
  }

  window.Snap = { attach };
})();
