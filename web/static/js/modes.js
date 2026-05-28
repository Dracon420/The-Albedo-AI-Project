/**
 * modes.js — View-mode switching for Albedo UI.
 *
 * Three modes:
 *   FULL   — Immersive fullscreen: hide neural links, expand orb, minimal topbar
 *   WINDOW — Standard cyberdeck layout (default)
 *   WIDGET — Opens widget.html in a compact floating Chrome app-mode window
 *
 * Persists the chosen mode to localStorage across sessions.
 * Syncs with Eel backend via eel.set_window_mode() so app.py can resize/reposition.
 */
(function () {
  "use strict";

  const PREF_KEY   = "albedo_view_mode";
  const MODE_FULL  = "fullscreen";
  const MODE_WIN   = "windowed";
  const MODE_WDGT  = "widget";

  /** Apply a mode class to <body> and update button states. */
  function applyMode(mode) {
    document.body.classList.remove(
      `mode--${MODE_FULL}`,
      `mode--${MODE_WIN}`,
      `mode--${MODE_WDGT}`
    );
    document.body.classList.add(`mode--${mode}`);

    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.mode === mode);
    });

    localStorage.setItem(PREF_KEY, mode);

    // Notify Eel backend (non-blocking, ignore errors when eel not ready)
    if (window.eel) {
      try { eel.set_window_mode(mode)(); } catch (_) {}
    }
  }

  /** Open the widget overlay in a second Chrome window via Eel. */
  function openWidget() {
    if (window.eel) {
      try { eel.open_widget_window()(); } catch (_) {}
    } else {
      // Fallback: try to open as a new tab/popup (won't be frameless)
      window.open(
        `${location.origin}/widget.html`,
        "albedo_widget",
        "width=380,height=560,menubar=no,toolbar=no,location=no,status=no"
      );
    }
  }

  /** Wire up the three mode buttons in the topbar. */
  function init() {
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.mode;
        if (mode === MODE_WDGT) {
          openWidget();
          // Don't change the main window's class — widget is a separate pane
          return;
        }
        applyMode(mode);
      });
    });

    // Restore previously saved mode (default: windowed)
    const saved = localStorage.getItem(PREF_KEY) || MODE_WIN;
    applyMode(saved !== MODE_WDGT ? saved : MODE_WIN); // widget can't auto-reopen
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Public
  window._modes = { applyMode, openWidget };
})();
