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
  }

  function open() {
    _drawer.classList.add("is-open");
    _scrim.classList.add("is-open");
    _drawer.setAttribute("aria-hidden", "false");
    _populate();
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

    _toggleBtn.addEventListener("click", toggle);
    _closeBtn .addEventListener("click", close);
    _scrim    .addEventListener("click", close);

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

    // Keyboard: Escape closes the drawer
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") close();
    });
  }

  return { init, open, close, toggle };
})();

window.Drawer = Drawer;
