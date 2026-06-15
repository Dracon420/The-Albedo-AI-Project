/**
 * brain_panel.js — BRAIN surface: pick the reasoning provider/model + autonomy.
 *
 * Host-agnostic: call BrainPanel.mount(rootEl) to render into any container
 * (a Mission Control drawer pane OR a standalone brain_window.html).
 *
 * Backend (albedo/eel_app/bridge.py):
 *   get_brain_config()  -> {ok, active_provider, active_model, available,
 *                           default_models, autonomy}
 *   set_brain_config(provider, model, autonomy) -> {ok, ...}
 */
(function () {
  "use strict";

  const AUTONOMY = [
    ["approve_all",         "Approve everything (safest)"],
    ["approve_destructive", "Approve destructive only"],
    ["full_auto",           "Full auto (no prompts)"],
  ];

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  async function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("panel", "panel--brain");

    const title = _el("div", "panel__title", "◈ BRAIN — REASONING CORE");
    root.appendChild(title);

    const status = _el("div", "panel__status", "loading…");
    root.appendChild(status);

    let cfg;
    try {
      cfg = await eel.get_brain_config()();
    } catch (e) {
      status.textContent = "bridge unavailable: " + e;
      return;
    }
    if (!cfg || !cfg.ok) {
      status.textContent = "error: " + (cfg && cfg.error || "unknown");
      return;
    }

    // ── Provider dropdown ──
    const provWrap = _el("label", "panel__field");
    provWrap.appendChild(_el("span", "panel__label", "Provider"));
    const provSel = _el("select", "panel__select");
    Object.entries(cfg.available || {}).forEach(([name, ready]) => {
      const o = _el("option", null, name + (ready ? "" : "  (no key)"));
      o.value = name;
      if (name === cfg.active_provider) o.selected = true;
      provSel.appendChild(o);
    });
    provWrap.appendChild(provSel);
    root.appendChild(provWrap);

    // ── Model field (placeholder shows the provider default) ──
    const modelWrap = _el("label", "panel__field");
    modelWrap.appendChild(_el("span", "panel__label", "Model"));
    const modelInput = _el("input", "panel__input");
    modelInput.type = "text";
    modelInput.value = cfg.active_model || "";
    modelInput.placeholder = (cfg.default_models || {})[cfg.active_provider] || "default";
    modelWrap.appendChild(modelInput);
    root.appendChild(modelWrap);

    // Update placeholder when provider changes
    provSel.addEventListener("change", () => {
      modelInput.placeholder = (cfg.default_models || {})[provSel.value] || "default";
    });

    // ── Autonomy radio ──
    const autoWrap = _el("div", "panel__field");
    autoWrap.appendChild(_el("span", "panel__label", "Autonomy"));
    const autoBox = _el("div", "panel__radio-group");
    AUTONOMY.forEach(([val, label]) => {
      const id = "brain-auto-" + val;
      const row = _el("label", "panel__radio");
      const r = _el("input");
      r.type = "radio"; r.name = "brain-autonomy"; r.value = val; r.id = id;
      if (val === (cfg.autonomy || "approve_all")) r.checked = true;
      row.appendChild(r);
      row.appendChild(_el("span", null, label));
      autoBox.appendChild(row);
    });
    autoWrap.appendChild(autoBox);
    root.appendChild(autoWrap);

    // ── Save ──
    const saveBtn = _el("button", "cmd-btn panel__save", "SAVE BRAIN");
    root.appendChild(saveBtn);
    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      const autonomy = (autoBox.querySelector("input:checked") || {}).value || "approve_all";
      try {
        const r = await eel.set_brain_config(provSel.value, modelInput.value.trim(), autonomy)();
        status.textContent = r && r.ok
          ? `saved: ${r.brain_provider || provSel.value} / ${r.agent_autonomy}`
          : "save error: " + (r && r.error || "unknown");
      } catch (e) {
        status.textContent = "save failed: " + e;
      } finally {
        saveBtn.disabled = false;
      }
    });

    status.textContent = `active: ${cfg.active_provider} / ${cfg.active_model}`;
  }

  window.BrainPanel = { mount };
})();
