// ============================================================
// chat.js — chat feed, input handling, send button, mode/wake toggles,
//           and the webhook update poller that surfaces remote commands
//           into the chat feed.
// ============================================================

const Chat = (() => {
  let _feedEl, _inputEl, _sendBtn, _micBtn, _scanBtn, _audioBtn, _modeBtn, _wakeBtn;
  let _audioMuted     = false;
  let _wakeProcessing = false;  // true while wake-word pipeline is running (SEND→STOP)
  let _commMode    = "latch";   // matches CommMode.LATCH.value
  let _wakeState   = "disarmed";
  let _personaName = "ALBEDO";  // display label — updated by wake word or settings

  function _ts() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `[${pad(d.getHours())}:${pad(d.getMinutes())}]`;
  }

  function appendLine(kind, text) {
    const line = document.createElement("div");
    line.className = `chat__line chat__line--${kind}`;
    line.textContent = `${_ts()} ${text}`;
    _feedEl.appendChild(line);
    _feedEl.scrollTop = _feedEl.scrollHeight;
  }

  async function _send() {
    // When the wake-word pipeline is running, the button reads "STOP" — intercept.
    if (_wakeProcessing) {
      try { await eel.stop_tts()(); } catch { /* ignore */ }
      return;
    }
    const raw = _inputEl.value.trim();
    if (!raw) return;
    _inputEl.value = "";
    _sendBtn.disabled = true;
    _sendBtn.textContent = "...";
    appendLine("user", "> " + raw);
    try {
      const r = await eel.send_query(raw, false)();
      if (r && r.ok) {
        appendLine("albedo", _personaName + "  " + (r.reply || "(no response)"));
      } else {
        appendLine("error", "[SYS] " + (r && r.error ? r.error : "no response"));
      }
    } catch (err) {
      appendLine("error", "[SYS] " + err);
    } finally {
      _sendBtn.disabled = false;
      _sendBtn.textContent = "SEND";
      _inputEl.focus();
    }
  }

  // ── Mode toggle (LATCH ↔ PTT) ────────────────────────────────────────
  function _renderMode() {
    if (!_modeBtn) return;
    _modeBtn.textContent = _commMode === "ptt" ? "MODE: PTT" : "MODE: LATCH";
    _modeBtn.setAttribute("data-state", _commMode === "ptt" ? "ptt" : "");
  }
  async function _toggleMode() {
    const next = _commMode === "latch" ? "ptt" : "latch";
    try {
      const r = await eel.set_comm_mode(next)();
      if (r && r.ok) {
        _commMode = r.mode;
        _renderMode();
        appendLine("system", `[SYS] MIC mode: ${_commMode === "ptt" ? "Push-to-Talk" : "Latch"}`);
      }
    } catch (err) { appendLine("error", "[SYS] " + err); }
  }

  // ── Wake-word arm/disarm ─────────────────────────────────────────────
  function _renderWake() {
    if (!_wakeBtn) return;
    _wakeBtn.textContent = _wakeState === "armed" ? "WAKE: ARMED" : "WAKE: OFF";
    _wakeBtn.setAttribute("data-state", _wakeState === "armed" ? "armed" : "");
  }
  async function _toggleWake() {
    const next = _wakeState === "armed" ? "disarmed" : "armed";
    try {
      const r = await eel.set_wake_state(next)();
      if (r && r.ok) {
        _wakeState = r.state;
        _renderWake();
        appendLine("system",
          `[SYS] Wake-word listener ${_wakeState === "armed" ? "ARMED" : "DISARMED"}`);
      }
    } catch (err) { appendLine("error", "[SYS] " + err); }
  }

  // ── Audio mute — synced to backend so wake-word TTS is also suppressed ──
  async function _toggleAudio() {
    _audioMuted = !_audioMuted;
    _audioBtn.classList.toggle("is-muted", _audioMuted);
    _audioBtn.textContent = _audioMuted ? "AUDIO: OFF" : "AUDIO: ON";
    try { await eel.set_audio_muted(_audioMuted)(); } catch { /* ignore */ }
  }

  // ── Webhook poller — drains pending remote commands into the feed ───
  async function _pollWebhook() {
    try {
      const r = await eel.pop_webhook_updates()();
      if (r && r.ok && Array.isArray(r.updates)) {
        for (const u of r.updates) {
          appendLine("system",
            `[WEBHOOK] ${u.source}: ${u.kind} ${JSON.stringify(u.payload || {})}`);
        }
      }
    } catch { /* ignore */ }
  }

  // ── Persona name — driven by wake word detection or settings panel ──────
  function _applyPersonaName(name) {
    _personaName = (name || "ALBEDO").toUpperCase();
    // Update the topbar brand so it matches the active persona
    const brand = document.getElementById("personaBrand");
    if (brand) brand.textContent = _personaName;
  }

  // Python pushes persona changes here when a wake word fires
  window._albedo_persona_push = function (name) { _applyPersonaName(name); };
  eel.expose(_albedo_persona_push, "_albedo_persona_push");

  // Python pushes chat lines here from backend threads (e.g. wake-word pipeline)
  window._albedo_chat_push = function (kind, text) { appendLine(kind, text); };
  eel.expose(_albedo_chat_push, "_albedo_chat_push");

  // Settings panel calls this when the user changes persona from the drawer
  window._albedo_persona_select = function (name) { _applyPersonaName(name); };

  // Python toggles SEND→STOP (true) / STOP→SEND (false) around wake pipeline
  window._albedo_send_stop = function(isStop) {
    _wakeProcessing = !!isStop;
    if (!_sendBtn) return;
    if (isStop) {
      _sendBtn.disabled  = false;
      _sendBtn.textContent = "STOP";
      _sendBtn.setAttribute("data-state", "stop");
    } else {
      _sendBtn.disabled  = false;
      _sendBtn.textContent = "SEND";
      _sendBtn.removeAttribute("data-state");
    }
  };
  eel.expose(_albedo_send_stop, "_albedo_send_stop");

  async function _initState() {
    try {
      const cm = await eel.get_comm_mode()();
      if (cm && cm.ok) { _commMode = cm.mode; _renderMode(); }
    } catch { /* ignore */ }
    try {
      const ws = await eel.get_wake_state()();
      if (ws && ws.ok) { _wakeState = ws.state; _renderWake(); }
    } catch { /* ignore */ }
    // Load persona name from backend (seeded from settings.json active_persona)
    try {
      const pn = await eel.get_active_persona_name()();
      if (pn && pn.ok && pn.name) _applyPersonaName(pn.name);
    } catch { /* ignore */ }
  }

  function init() {
    _feedEl   = document.getElementById("chat");
    _inputEl  = document.getElementById("queryInput");
    _sendBtn  = document.getElementById("sendBtn");
    _micBtn   = document.getElementById("micBtn");
    _scanBtn  = document.getElementById("scanBtn");
    _audioBtn = document.getElementById("audioBtn");
    _modeBtn  = document.getElementById("modeBtn");
    _wakeBtn  = document.getElementById("wakeBtn");

    _sendBtn .addEventListener("click", _send);
    _inputEl .addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") _send();
    });
    _audioBtn.addEventListener("click", _toggleAudio);
    _modeBtn .addEventListener("click", _toggleMode);
    _wakeBtn .addEventListener("click", _toggleWake);

    // MIC: trigger voice capture via the backend pipeline
    _micBtn.addEventListener("click", async () => {
      appendLine("system", "[SYS] MIC activated — listening...");
      try {
        const r = await eel.trigger_mic_capture()();
        if (r && r.ok && r.text) {
          // Treat the transcribed text as a typed query
          _inputEl.value = r.text;
          appendLine("user", "> " + r.text);
          _inputEl.value = "";
          _sendBtn.disabled = true;
          _sendBtn.textContent = "...";
          try {
            const qr = await eel.send_query(r.text, false)();
            if (qr && qr.ok) {
              appendLine("albedo", _personaName + "  " + (qr.reply || "(no response)"));
            } else {
              appendLine("error", "[SYS] " + (qr && qr.error ? qr.error : "no response"));
            }
          } finally {
            _sendBtn.disabled = false;
            _sendBtn.textContent = "SEND";
          }
        } else if (r && r.error) {
          appendLine("error", "[SYS] MIC: " + r.error);
        } else {
          appendLine("system", "[SYS] MIC: nothing captured.");
        }
      } catch (e) {
        appendLine("error", "[SYS] MIC error: " + e);
      }
    });
    _scanBtn.addEventListener("click", async () => {
      appendLine("system", "[SYS] SCAN capturing screen...");
      try {
        const r = await eel.trigger_scan_capture()();
        if (r && r.ok && r.description) {
          appendLine("albedo", _personaName + "  " + r.description);
        } else if (r && r.error) {
          appendLine("error", "[SYS] SCAN: " + r.error);
        } else {
          appendLine("system", "[SYS] SCAN: no result.");
        }
      } catch (e) {
        appendLine("error", "[SYS] SCAN error: " + e);
      }
    });

    _initState();
    setInterval(_pollWebhook, 1500);
    _inputEl.focus();
  }

  return { init, appendLine };
})();

window.Chat = Chat;
