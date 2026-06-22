/**
 * profile_popup.js — "About You" form so Albedo can learn the user.
 *
 * Opens when the agent runs open_user_profile (via the event bus), or on demand
 * via window._albedo_show_profile(). Fields are saved to user_profile.json and
 * fed into Albedo's system prompt so every reply is personalised.
 *
 * Reuses the .apps-modal styling.
 */
(function () {
  "use strict";

  const FIELDS = [
    ["name",       "Name",              "input", "What should I call you?"],
    ["age",        "Age",               "input", ""],
    ["occupation", "Job / role",        "input", "e.g. 3D printing, sysadmin…"],
    ["location",   "Location",          "input", "City / timezone (optional)"],
    ["hobbies",    "Hobbies / interests", "area", "Reptiles, Exotic OS, printing…"],
    ["goals",      "Goals",             "area", "What are you working toward?"],
    ["about",      "Anything else",     "area", "Anything you want me to know"],
  ];

  let _modal = null, _inputs = {};

  function _ensure() {
    if (_modal) return;
    _modal = document.createElement("div");
    _modal.className = "apps-modal profile-modal";
    const rows = FIELDS.map(([key, label, kind, ph]) => {
      const ctrl = kind === "area"
        ? `<textarea class="profile-field" data-k="${key}" rows="2" placeholder="${ph}"></textarea>`
        : `<input class="profile-field" data-k="${key}" type="text" placeholder="${ph}">`;
      return `<label class="profile-row"><span class="profile-row__label">${label}</span>${ctrl}</label>`;
    }).join("");
    _modal.innerHTML = `
      <div class="apps-modal__box">
        <div class="apps-modal__head">
          <span>ABOUT YOU &mdash; help Albedo learn you</span>
          <button class="apps-modal__x" title="Close">&times;</button>
        </div>
        <div class="apps-modal__hint">
          Stored locally in user_profile.json and used to personalise replies.
          Leave anything blank.
        </div>
        <div class="apps-modal__list profile-grid">${rows}</div>
        <div class="apps-modal__foot">
          <button class="cmd-btn cmd-btn--accent profile-save">SAVE PROFILE</button>
          <button class="cmd-btn profile-close">CLOSE</button>
        </div>
      </div>`;
    document.body.appendChild(_modal);
    _modal.querySelectorAll(".profile-field").forEach((el) => { _inputs[el.dataset.k] = el; });
    _modal.querySelector(".apps-modal__x").onclick = close;
    _modal.querySelector(".profile-close").onclick = close;
    _modal.querySelector(".profile-save").onclick = _save;
    _modal.addEventListener("click", (e) => { if (e.target === _modal) close(); });
  }

  function close() { if (_modal) _modal.classList.remove("is-open"); }

  async function open() {
    _ensure();
    _modal.classList.add("is-open");
    try {
      const r = await eel.get_user_profile()();
      const p = (r && r.profile) || {};
      Object.keys(_inputs).forEach((k) => { _inputs[k].value = p[k] || ""; });
    } catch (e) { /* leave blank */ }
    const first = _inputs.name; if (first) first.focus();
  }

  async function _save() {
    const data = {};
    Object.keys(_inputs).forEach((k) => { data[k] = _inputs[k].value.trim(); });
    const btn = _modal.querySelector(".profile-save");
    btn.disabled = true; btn.textContent = "SAVING…";
    try { await eel.save_user_profile(data)(); btn.textContent = "SAVED ✓"; }
    catch (e) { btn.textContent = "SAVE FAILED"; }
    setTimeout(() => { btn.disabled = false; btn.textContent = "SAVE PROFILE"; close(); }, 700);
  }

  window._albedo_show_profile = function () { open(); };
  if (window.eel) { try { eel.expose(_albedo_show_profile, "_albedo_show_profile"); } catch (_) {} }

  // Auto-open when the agent invokes open_user_profile.
  (function wire() {
    if (window.EventBus) {
      EventBus.on("tool.result", (e) => {
        if (e && e.name === "open_user_profile") open();
      });
    } else { setTimeout(wire, 300); }
  })();
})();
