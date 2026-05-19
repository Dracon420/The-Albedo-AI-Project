// ============================================================
// settings.js — Tactical Drawer "SETTINGS" pane wiring.
//
// On first drawer open (or on Settings tab activation), pulls
// the current settings + the choice enums from eel.get_settings(),
// and the device list from eel.get_audio_devices(). Populates the
// dropdowns / slider, then attaches change handlers that round-trip
// through eel.set_setting(key, value).
//
// Saved values land in install-root settings.json — the same file
// the Tk GUI reads/writes — so the two UIs stay in sync if the user
// switches back and forth via ALBEDO_UI.
// ============================================================

const Settings = (() => {
  let _personaSel, _audioInSel, _audioOutSel,
      _visionRange, _visionVal, _autoUpdateSel;
  let _populated = false;
  let _silent    = false;   // flips true during programmatic .value writes
                            // so the change handlers don't echo back to disk

  function _fillSelect(sel, options, currentValue, formatter) {
    sel.innerHTML = "";
    for (const opt of options) {
      const value = (typeof opt === "object") ? opt.value : opt;
      const label = (typeof opt === "object") ? opt.label : (formatter ? formatter(opt) : opt);
      const el = document.createElement("option");
      el.value = String(value);
      el.textContent = label;
      if (String(value) === String(currentValue)) el.selected = true;
      sel.appendChild(el);
    }
  }

  function _setRangePercent(input, value, min, max) {
    const pct = Math.round(((value - min) / (max - min)) * 100);
    input.style.setProperty("--pct", pct + "%");
  }

  async function _populate() {
    if (_populated) return;
    _populated = true;

    let s, devs;
    try { s    = await eel.get_settings()();        } catch { s    = { ok: false }; }
    try { devs = await eel.get_audio_devices()();   } catch { devs = { ok: false }; }
    if (!s || !s.ok) {
      console.warn("[settings] get_settings failed:", s && s.error);
      return;
    }
    const cur     = s.settings || {};
    const choices = s.choices  || {};

    _silent = true;

    // Persona
    _fillSelect(_personaSel,
      (choices.active_persona || ["cortana"]).map(v => ({
        value: v,
        label: v.charAt(0).toUpperCase() + v.slice(1),
      })),
      cur.active_persona);

    // Audio devices — empty + each detected device
    if (devs && devs.ok) {
      const fmt = (d) => `${d.index} — ${d.name}` + (d.default ? "  (default)" : "");
      _fillSelect(_audioInSel,
        [{value: "", label: "(system default)"}].concat(
          devs.inputs.map(d => ({value: d.index, label: fmt(d)}))),
        cur.audio_input_device === null || cur.audio_input_device === undefined
          ? "" : cur.audio_input_device);
      _fillSelect(_audioOutSel,
        [{value: "", label: "(system default)"}].concat(
          devs.outputs.map(d => ({value: d.index, label: fmt(d)}))),
        cur.audio_output_device === null || cur.audio_output_device === undefined
          ? "" : cur.audio_output_device);
    } else {
      // sounddevice unavailable — disable the selects with a placeholder
      [_audioInSel, _audioOutSel].forEach(s => {
        s.innerHTML = "<option>(audio devices unavailable)</option>";
        s.disabled = true;
      });
    }

    // Vision temperature
    const range = choices.vision_temperature || { min: 0, max: 1, step: 0.05 };
    _visionRange.min   = range.min;
    _visionRange.max   = range.max;
    _visionRange.step  = range.step;
    _visionRange.value = cur.vision_temperature ?? 0.2;
    _visionVal.textContent = Number(_visionRange.value).toFixed(2);
    _setRangePercent(_visionRange, Number(_visionRange.value), range.min, range.max);

    // Auto-update interval
    _fillSelect(_autoUpdateSel,
      choices.auto_update || ["Every 24 hours"],
      cur.auto_update);

    _silent = false;
  }

  async function _persist(key, value) {
    if (_silent) return;
    try {
      const r = await eel.set_setting(key, value)();
      if (!r || !r.ok) console.warn("[settings] set_setting failed:", r && r.error);
    } catch (err) {
      console.warn("[settings] set_setting error:", err);
    }
  }

  // ── Memory subsystem: Obsidian index + REM dream cycle ────────────
  async function _runMemoryAction(label, eelFn, btnEl, statusEl) {
    if (!btnEl) return;
    const originalText = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = label + " ...";
    if (statusEl) statusEl.textContent = "// " + label.toLowerCase() + " in progress";
    try {
      const r = await eelFn();
      if (r && r.ok) {
        if (statusEl) statusEl.textContent = "// " + (r.status || (label + " complete"));
        if (window.Chat && Chat.appendLine) {
          Chat.appendLine("system", "[MEMORY] " + (r.status || label + " complete"));
        }
      } else {
        const err = (r && r.error) || "unknown error";
        if (statusEl) statusEl.textContent = "// FAIL: " + err;
        if (window.Chat && Chat.appendLine) {
          Chat.appendLine("error", "[MEMORY] " + label + " failed: " + err);
        }
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = "// FAIL: " + err;
      if (window.Chat && Chat.appendLine) {
        Chat.appendLine("error", "[MEMORY] " + label + " error: " + err);
      }
    } finally {
      btnEl.disabled = false;
      btnEl.textContent = originalText;
    }
  }

  function init() {
    _personaSel    = document.getElementById("personaSelect");
    _audioInSel    = document.getElementById("audioInSelect");
    _audioOutSel   = document.getElementById("audioOutSelect");
    _visionRange   = document.getElementById("visionTempRange");
    _visionVal     = document.getElementById("visionTempVal");
    _autoUpdateSel = document.getElementById("autoUpdateSelect");
    const indexBtn  = document.getElementById("indexVaultBtn");
    const dreamBtn  = document.getElementById("dreamCycleBtn");
    const memStatus = document.getElementById("memoryStatus");

    if (indexBtn) indexBtn.addEventListener("click",
      () => _runMemoryAction("REBUILD INDEX",  () => eel.index_obsidian_vault()(),  indexBtn, memStatus));
    if (dreamBtn) dreamBtn.addEventListener("click",
      () => _runMemoryAction("REM CYCLE",      () => eel.initiate_dream_cycle()(),  dreamBtn, memStatus));

    if (!_personaSel) return;        // drawer missing — skip silently

    // Change handlers
    _personaSel   .addEventListener("change", (e) => _persist("active_persona", e.target.value));
    _audioInSel   .addEventListener("change", (e) => {
      const v = e.target.value === "" ? null : parseInt(e.target.value, 10);
      _persist("audio_input_device", v);
    });
    _audioOutSel  .addEventListener("change", (e) => {
      const v = e.target.value === "" ? null : parseInt(e.target.value, 10);
      _persist("audio_output_device", v);
    });
    _visionRange  .addEventListener("input", (e) => {
      const v = Number(e.target.value);
      _visionVal.textContent = v.toFixed(2);
      _setRangePercent(_visionRange, v,
                       Number(_visionRange.min), Number(_visionRange.max));
    });
    _visionRange  .addEventListener("change", (e) => _persist("vision_temperature", Number(e.target.value)));
    _autoUpdateSel.addEventListener("change", (e) => _persist("auto_update", e.target.value));

    // Drawer open is the cheapest trigger — populate when the drawer toggle
    // is clicked OR when SETTINGS tab is clicked, whichever comes first.
    const toggleBtn = document.getElementById("drawerToggle");
    if (toggleBtn) toggleBtn.addEventListener("click", _populate, { once: true });
    document.querySelectorAll('.drawer__tab[data-tab="settings"]').forEach((t) => {
      t.addEventListener("click", _populate, { once: true });
    });
  }

  return { init, populate: _populate };
})();

window.Settings = Settings;
