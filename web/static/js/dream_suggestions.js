/**
 * dream_suggestions.js — surfaces dream-cycle file-move suggestions at boot.
 *
 * The dream cycle no longer moves files autonomously (it over-organized before).
 * It now proposes moves and writes them to dream_pending_moves.json. This module
 * checks for pending suggestions shortly after the UI comes online and, if any
 * exist, shows a cyan modal listing every proposed move with APPROVE ALL /
 * DECLINE buttons. Nothing moves unless the user clicks APPROVE.
 *
 * Backend bridge fns (albedo/eel_app/bridge.py):
 *   get_dream_file_suggestions()     -> {ok, count, moves:[{src,dest,category}]}
 *   apply_dream_file_suggestions()   -> {ok, applied, moves}
 *   discard_dream_file_suggestions() -> {ok, discarded}
 */
(function () {
  "use strict";

  let _modal, _list, _meta, _approveBtn, _declineBtn, _wired = false;

  function _refs() {
    _modal      = document.getElementById("dreamSuggestModal");
    _list       = document.getElementById("dreamSuggestList");
    _meta       = document.getElementById("dreamSuggestMeta");
    _approveBtn = document.getElementById("dreamSuggestApprove");
    _declineBtn = document.getElementById("dreamSuggestDecline");
    return _modal && _list && _approveBtn && _declineBtn;
  }

  function _basename(p) {
    if (!p) return "";
    const parts = String(p).split(/[\\/]/);
    return parts[parts.length - 1] || p;
  }

  function _show() { _modal.classList.add("is-visible"); _modal.setAttribute("aria-hidden", "false"); }
  function _hide() { _modal.classList.remove("is-visible"); _modal.setAttribute("aria-hidden", "true"); }

  function _render(moves) {
    _list.innerHTML = "";
    moves.forEach((m) => {
      const row = document.createElement("div");
      row.className = "dream-modal__row";
      const cat = document.createElement("span");
      cat.className = "dream-modal__cat";
      cat.textContent = m.category || "Misc";
      const fname = document.createElement("span");
      fname.className = "dream-modal__fname";
      fname.textContent = _basename(m.src) + "  →  " + (m.category || "Misc") + "/";
      row.appendChild(cat);
      row.appendChild(fname);
      _list.appendChild(row);
    });
    if (_meta) {
      _meta.textContent =
        `Albedo proposed ${moves.length} file move(s) while idle. ` +
        `Nothing has been moved yet — review and choose.`;
    }
  }

  function _wireButtons() {
    if (_wired) return;
    _wired = true;

    _approveBtn.addEventListener("click", async () => {
      _approveBtn.disabled = true;
      _declineBtn.disabled = true;
      try {
        const r = await eel.apply_dream_file_suggestions()();
        const n = (r && r.ok) ? r.applied : 0;
        if (window.Chat && Chat.appendLine) {
          Chat.appendLine("system", `[DREAM] Applied ${n} approved file move(s).`);
        }
      } catch (e) {
        if (window.Chat && Chat.appendLine) {
          Chat.appendLine("error", "[DREAM] Apply failed: " + e);
        }
      } finally {
        _hide();
        _approveBtn.disabled = false;
        _declineBtn.disabled = false;
      }
    });

    _declineBtn.addEventListener("click", async () => {
      _approveBtn.disabled = true;
      _declineBtn.disabled = true;
      try {
        const r = await eel.discard_dream_file_suggestions()();
        const n = (r && r.ok) ? r.discarded : 0;
        if (window.Chat && Chat.appendLine) {
          Chat.appendLine("system", `[DREAM] Declined ${n} suggestion(s) — nothing moved.`);
        }
      } catch (e) {
        /* non-fatal */
      } finally {
        _hide();
        _approveBtn.disabled = false;
        _declineBtn.disabled = false;
      }
    });
  }

  async function _check() {
    if (!_refs()) return;
    try {
      const r = await eel.get_dream_file_suggestions()();
      if (!r || !r.ok || !r.count) return;   // nothing pending
      _wireButtons();
      _render(r.moves || []);
      _show();
    } catch (e) {
      /* bridge not ready or no suggestions — ignore */
    }
  }

  function _whenReady(cb) {
    if (typeof eel !== "undefined" && eel.get_dream_file_suggestions) {
      cb();
    } else {
      setTimeout(() => _whenReady(cb), 200);
    }
  }

  // Check a few seconds after load so it doesn't fight the boot sequence.
  document.addEventListener("DOMContentLoaded", () => {
    _whenReady(() => setTimeout(_check, 2500));
  });

  // Expose for manual re-check (e.g. after a forced dream cycle completes).
  window._dreamSuggestions = { check: _check };
})();
