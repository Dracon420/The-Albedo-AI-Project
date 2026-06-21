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

    // ── Model dropdown (curated list per provider; "Custom…" for any id) ──
    const modelsByProvider = cfg.models_by_provider || {};
    const CUSTOM = "__custom__";

    const modelWrap = _el("label", "panel__field");
    modelWrap.appendChild(_el("span", "panel__label", "Model"));
    const modelSel = _el("select", "panel__select");
    modelWrap.appendChild(modelSel);
    root.appendChild(modelWrap);

    // Hidden text box, revealed only when "Custom…" is selected.
    const customWrap = _el("label", "panel__field");
    customWrap.style.display = "none";
    customWrap.appendChild(_el("span", "panel__label", "Custom model id"));
    const customInput = _el("input", "panel__input");
    customInput.type = "text";
    customInput.placeholder = "exact provider model id";
    customWrap.appendChild(customInput);
    root.appendChild(customWrap);

    // (Re)build the model options for a provider, pre-selecting `selected`.
    function populateModels(provider, selected) {
      modelSel.innerHTML = "";
      const dflt = (cfg.default_models || {})[provider] || "";
      const list = (modelsByProvider[provider] || []).slice();
      if (dflt && !list.includes(dflt)) list.unshift(dflt);

      list.forEach((m) => {
        const o = _el("option", null, m + (m === dflt ? "  (default)" : ""));
        o.value = m;
        modelSel.appendChild(o);
      });
      const customOpt = _el("option", null, "Custom…");
      customOpt.value = CUSTOM;
      modelSel.appendChild(customOpt);

      if (selected && list.includes(selected)) {
        modelSel.value = selected;
        customWrap.style.display = "none";
      } else if (selected) {                // a model not in the list → custom
        modelSel.value = CUSTOM;
        customInput.value = selected;
        customWrap.style.display = "";
      } else {                              // provider switch → its default
        modelSel.value = dflt || (list[0] || CUSTOM);
        customWrap.style.display = (modelSel.value === CUSTOM) ? "" : "none";
      }
    }
    populateModels(cfg.active_provider, cfg.active_model);

    modelSel.addEventListener("change", () => {
      customWrap.style.display = (modelSel.value === CUSTOM) ? "" : "none";
    });
    // Switching provider rebuilds the model list to that provider's default.
    provSel.addEventListener("change", () => populateModels(provSel.value, ""));

    // Resolve the chosen model id at save time (dropdown value or custom text).
    function chosenModel() {
      return modelSel.value === CUSTOM ? customInput.value.trim() : modelSel.value;
    }

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
        const r = await eel.set_brain_config(provSel.value, chosenModel(), autonomy)();
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
