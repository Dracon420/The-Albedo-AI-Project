// ============================================================
// drawer.js — open/close the off-canvas Tactical Drawer + populate
//             the diagnostic readouts the first time it opens.
// ============================================================

const Drawer = (() => {
  let _drawer, _scrim, _toggleBtn, _closeBtn;
  let _populated = false;

  function _renderHardware(hw) {
    if (!hw) return "(no data)";
    const cpu = hw.cpu || {};
    const gpu = hw.gpu || {};
    const ram = hw.ram || {};
    const plat = hw.platform || {};
    return [
      `CPU      ${cpu.short || "?"}   (${cpu.cores_physical || "?"}p / ${cpu.cores_logical || "?"}l)`,
      `         ${cpu.raw || ""}`,
      ``,
      `GPU      ${gpu.short || "?"}   ${gpu.vram_mb ? gpu.vram_mb + " MB" : ""}`,
      `         ${gpu.raw || ""}`,
      ``,
      `RAM      ${ram.total_gb || "?"} GB`,
      ``,
      `OS       ${plat.system || "?"} ${plat.release || ""} (${plat.machine || ""})`,
      `Cached   ${hw.cached_at || "—"}`,
    ].join("\n");
  }

  function _renderResources(resMap) {
    if (!resMap) return "(no data)";
    const rows = [];
    for (const [name, e] of Object.entries(resMap)) {
      const tag = e.demoted ? `${e.device}  (demoted: ${e.demoted})` : e.device;
      const eager = e.eager ? "eager" : "lazy";
      rows.push(`${name.padEnd(14)} ${(e.runtime || "?").padEnd(8)} ${tag.padEnd(34)} ${eager}`);
    }
    return rows.join("\n") || "(empty)";
  }

  // ── Dream status helpers ──────────────────────────────────────────────────
  let _dreamEl = null;

  function _setDreamText(text) {
    if (!_dreamEl) _dreamEl = document.getElementById("dreamStatus");
    if (_dreamEl) _dreamEl.textContent = text;
  }

  // Eel push from Python (called by _dream_status_push in bridge.py)
  window._albedo_dream_push = function (label) {
    _setDreamText(label);
  };
  eel.expose(_albedo_dream_push, "_albedo_dream_push");

  // ── Query-latency readout (albedo.perf via get_perf_timings) ─────────────
  async function _refreshPerf() {
    const el = document.getElementById("perfReadout");
    if (!el) return;
    try {
      const r = await eel.get_perf_timings(10)();
      if (!r || !r.ok || !Array.isArray(r.data) || !r.data.length) {
        el.textContent = "// no queries yet";
        return;
      }
      // newest first
      const lines = r.data.slice().reverse().map((t) => {
        const stages = (t.stages || [])
          .map((s) => `${s[0]} ${Math.round(s[1])}ms`).join("  ");
        const route = String(t.route || "?").padEnd(13).slice(0, 13);
        const total = `${Math.round(t.total_ms || 0)}ms`.padStart(7);
        return `${route}${total}   ${stages}`;
      });
      el.textContent = lines.join("\n");
    } catch (_) { /* ignore */ }
  }

  async function _refreshDreamState() {
    try {
      const r = await eel.get_dream_state()();
      if (!r || !r.ok) return;
      let text = `// dream: ${(r.state || "idle").toLowerCase()}`;
      if (r.report && r.report.summary) {
        text += `\n// last: ${r.report.summary}`;
      }
      _setDreamText(text);
    } catch { /* ignore */ }
  }

  async function _populate() {
    if (_populated) return;
    _populated = true;
    try {
      const v = await eel.get_version()();
      document.getElementById("versionReadout").textContent =
        `Albedo v${v.version}\nUI       eel\nUptime   ${v.uptime_s}s`;
    } catch { /* ignore */ }
    try {
      const hw = await eel.get_hardware_profile()();
      document.getElementById("hwReadout").textContent =
        hw.ok ? _renderHardware(hw.data) : "(error)";
    } catch { /* ignore */ }
    try {
      const rm = await eel.get_resource_map()();
      document.getElementById("resourceReadout").textContent =
        rm.ok ? _renderResources(rm.data) : "(error)";
    } catch { /* ignore */ }
    // Populate dream state on first open
    _refreshDreamState();

    // Populate idle threshold label from backend config
    try {
      const cfg = await eel.get_config_values(["IDLE_THRESHOLD_MINUTES"])();
      if (cfg && cfg.ok && cfg.data) {
        const el = document.getElementById("idleThresholdLabel");
        if (el && cfg.data["IDLE_THRESHOLD_MINUTES"] != null) {
          el.textContent = cfg.data["IDLE_THRESHOLD_MINUTES"];
        }
      }
    } catch { /* ignore — defaults to 20 shown in HTML */ }
  }

  function open() {
    _drawer.classList.add("is-open");
    _scrim.classList.add("is-open");
    _drawer.setAttribute("aria-hidden", "false");
    _populate();
    _refreshPerf();   // latency readout — refresh every time the drawer opens
  }
  function close() {
    _drawer.classList.remove("is-open");
    _scrim.classList.remove("is-open");
    _drawer.setAttribute("aria-hidden", "true");
  }
  function toggle() {
    if (_drawer.classList.contains("is-open")) close();
    else open();
  }

  function _setBackground(bgKey) {
    document.body.setAttribute("data-background", bgKey);
    document.querySelectorAll(".drawer__bg-thumb").forEach((t) => {
      t.classList.toggle("is-active", t.getAttribute("data-bg") === bgKey);
    });
    // Persist locally so it sticks across reloads in the same browser.
    try { localStorage.setItem("albedo-bg", bgKey); } catch { /* ignore */ }
  }

  function _switchTab(name) {
    document.querySelectorAll(".drawer__tab").forEach((t) =>
      t.classList.toggle("is-active", t.dataset.tab === name));
    document.querySelectorAll(".drawer__pane").forEach((p) =>
      p.classList.toggle("is-active", p.dataset.pane === name));
  }

  function init() {
    _drawer    = document.getElementById("drawer");
    _scrim     = document.getElementById("drawerScrim");
    _toggleBtn = document.getElementById("drawerToggle");
    _closeBtn  = document.getElementById("drawerClose");

    const missing = [["drawer",_drawer],["drawerScrim",_scrim],
                     ["drawerToggle",_toggleBtn],["drawerClose",_closeBtn]]
                    .filter(([,el]) => !el).map(([id]) => id);
    if (missing.length) throw new Error("missing IDs: " + missing.join(", "));

    _toggleBtn.addEventListener("click", toggle);
    _closeBtn .addEventListener("click", close);
    _scrim    .addEventListener("click", close);

    // Pin / unpin — turns the drawer into a permanent right-side sidebar
    // (toggled via body.is-pinned in drawer.css). State persists across reloads.
    const _pinBtn = document.getElementById("drawerPinBtn");
    if (_pinBtn) {
      function _applyPin(pinned) {
        document.body.classList.toggle("is-pinned", !!pinned);
        _pinBtn.setAttribute("aria-pressed", pinned ? "true" : "false");
        _pinBtn.title = pinned ? "Unpin drawer" : "Pin / unpin as right-side sidebar";
        if (pinned) open();  // make sure it's visible when pinned
      }
      let _pinned = false;
      try { _pinned = localStorage.getItem("albedo-drawer-pinned") === "1"; } catch (_) {}
      _applyPin(_pinned);
      _pinBtn.addEventListener("click", () => {
        _pinned = !_pinned;
        try { localStorage.setItem("albedo-drawer-pinned", _pinned ? "1" : "0"); } catch (_) {}
        _applyPin(_pinned);
      });
    }

    // Tab switcher
    document.querySelectorAll(".drawer__tab").forEach((t) => {
      t.addEventListener("click", () => _switchTab(t.dataset.tab));
    });

    // Background thumbnails
    document.querySelectorAll(".drawer__bg-thumb").forEach((t) => {
      t.addEventListener("click", () => _setBackground(t.getAttribute("data-bg")));
    });

    // Restore stored background
    let stored = null;
    try { stored = localStorage.getItem("albedo-bg"); } catch { /* ignore */ }
    if (stored) _setBackground(stored);
    else        _setBackground(document.body.getAttribute("data-background") || "bg2");

    // ── Dream cycle force button ──────────────────────────────────────────
    const dreamForceBtn = document.getElementById("dreamForceBtn");
    if (dreamForceBtn) {
      dreamForceBtn.addEventListener("click", async () => {
        dreamForceBtn.disabled = true;
        dreamForceBtn.textContent = "DREAMING…";
        _setDreamText("// dream: initiating forced cycle...\n// phases 1/3 → 2/3 → 3/3");
        try {
          const r = await eel.force_dream_cycle()();
          if (!r || !r.ok) {
            _setDreamText(`// dream: ${r ? r.error : "bridge error"}`);
            dreamForceBtn.disabled = false;
            dreamForceBtn.textContent = "FORCE DREAM NOW";
          }
          // Status updates flow in via window._albedo_dream_push as phases complete
        } catch (e) {
          _setDreamText(`// dream: error — ${e}`);
          dreamForceBtn.disabled = false;
          dreamForceBtn.textContent = "FORCE DREAM NOW";
        }
      });

      // Re-enable the button whenever the dream cycle returns to IDLE/COOLDOWN
      const _watchDream = setInterval(async () => {
        if (!dreamForceBtn.disabled) return;
        try {
          const r = await eel.get_dream_state()();
          if (r && r.ok && r.state !== "DREAMING") {
            dreamForceBtn.disabled = false;
            dreamForceBtn.textContent = "FORCE DREAM NOW";
            clearInterval(_watchDream);
          }
        } catch { /* ignore */ }
      }, 5000);
    }

    // ── Update checker ────────────────────────────────────────────────────
    const checkUpdateBtn    = document.getElementById("checkUpdateBtn");
    const updateStatus      = document.getElementById("updateStatus");
    const updateDownloadLink = document.getElementById("updateDownloadLink");

    if (checkUpdateBtn) {
      checkUpdateBtn.addEventListener("click", async () => {
        checkUpdateBtn.disabled = true;
        checkUpdateBtn.textContent = "CHECKING…";
        if (updateStatus)      updateStatus.textContent = "// contacting GitHub...";
        if (updateDownloadLink) updateDownloadLink.style.display = "none";

        try {
          const r = await eel.check_for_update()();
          if (!r || !r.ok) {
            if (updateStatus)
              updateStatus.textContent = `// check failed: ${r ? r.error : "no response"}`;
          } else if (r.up_to_date) {
            if (updateStatus)
              updateStatus.textContent = `// up to date — v${r.current} is the latest`;
          } else {
            if (updateStatus)
              updateStatus.textContent =
                `// update available!\n// current: v${r.current}\n// latest:  v${r.latest}`;
            if (updateDownloadLink && r.release_url) {
              updateDownloadLink.href = r.release_url;
              updateDownloadLink.style.display = "block";
            }
          }
        } catch (e) {
          if (updateStatus) updateStatus.textContent = `// error: ${e}`;
        } finally {
          checkUpdateBtn.disabled = false;
          checkUpdateBtn.textContent = "CHECK FOR UPDATE";
        }
      });
    }

    // Keep the QUERY LATENCY readout live — it otherwise only refreshed on
    // drawer-open, so a PINNED drawer never updated after a query.
    setInterval(_refreshPerf, 3000);

    // Keyboard: Escape closes the drawer
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") close();
    });
  }

  return { init, open, close, toggle };
})();

window.Drawer = Drawer;
