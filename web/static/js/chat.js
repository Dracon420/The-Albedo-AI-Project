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
  const _history = [];          // rolling {role, content} so Albedo remembers the conversation

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
      // Auto-router path: Albedo decides direct-answer vs. spin-up-team.
      // Live team/RAG activity shows in the Team + Brain visualization windows.
      const r = await eel.send_chat(raw, _history.slice(-10))();
      if (r && r.ok) {
        if (r.mode === "team") {
          appendLine("system", "[TEAM activated — see Team window for live progress]");
        }
        // Streamed answers are already typing; otherwise type the full answer
        // out at reading pace too.
        if (!r.streamed && r.mode !== "team") {
          _twMessage("albedo", _personaName + "  " + (r.answer || "(no response)"),
                     `${_ts()} `);
        }
        // Remember the exchange so follow-ups ("yes please") keep context.
        if (r.mode !== "team" && r.answer) {
          _history.push({ role: "user", content: raw });
          _history.push({ role: "assistant", content: r.answer });
        }
      } else {
        _twClose();
        appendLine("error", "[SYS] " + (r && r.error ? r.error : "no response"));
      }
    } catch (err) {
      _clearStatus();
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

  // ── Live activity status ("thinking…", "checking installed apps…") ────────
  // An ephemeral line the backend updates as the agent works, so the user can
  // follow progress and knows it isn't stalled. Cleared when the answer starts.
  let _statusEl = null;
  function _showStatus(text) {
    if (!_feedEl || !text) return;
    if (!_statusEl) {
      _statusEl = document.createElement("div");
      _statusEl.className = "chat__line chat__line--status";
      _feedEl.appendChild(_statusEl);
    }
    _statusEl.textContent = `${_ts()} ⋯ ${text}`;
    _feedEl.scrollTop = _feedEl.scrollHeight;
  }
  function _clearStatus() {
    if (_statusEl) { _statusEl.remove(); _statusEl = null; }
  }
  window._albedo_chat_status = function (text) { _showStatus(text); };
  eel.expose(_albedo_chat_status, "_albedo_chat_status");

  // ── Typewriter queue — reveals text at a steady reading pace ──────────────
  // Every Albedo answer (streamed tokens OR a full pushed message) flows through
  // this queue so text never pops in all at once. Messages type out FIFO; a
  // streaming message stays "open" and accepts more tokens until closed.
  const _tw = { q: [], timer: null, STEP_MS: 18 };

  function _twPump() {
    if (_tw.timer) return;
    _tw.timer = setInterval(() => {
      const m = _tw.q[0];
      if (!m) { clearInterval(_tw.timer); _tw.timer = null; return; }
      if (!m.el) {
        m.el = document.createElement("div");
        m.el.className = `chat__line chat__line--${m.kind}`;
        m.el.textContent = m.prefix;
        _feedEl.appendChild(m.el);
      }
      const remaining = m.full.length - m.shown;
      if (remaining > 0) {
        // reveal a few chars/tick; speed up when a big backlog is queued
        const step = Math.min(remaining, Math.max(1, Math.ceil(remaining / 22)));
        m.shown += step;
        m.el.textContent = m.prefix + m.full.slice(0, m.shown);
        _feedEl.scrollTop = _feedEl.scrollHeight;
      } else if (m.closed) {
        _tw.q.shift();   // fully revealed + closed → advance to next message
      }
    }, _tw.STEP_MS);
  }
  function _twOpen(kind, prefix) {
    const m = { kind, prefix, full: "", shown: 0, closed: false, el: null };
    _tw.q.push(m);
    _twPump();
    return m;
  }
  function _twToken(tok) {
    _clearStatus();   // the answer is arriving — drop the "thinking…" line
    let m = _tw.q[_tw.q.length - 1];
    if (!m || m.closed) m = _twOpen("albedo", `${_ts()} ${_personaName}  `);
    m.full += tok;
    _twPump();
  }
  function _twClose() {
    const m = _tw.q[_tw.q.length - 1];
    if (m) m.closed = true;
  }
  function _twMessage(kind, text, prefix) {
    _clearStatus();
    const m = _twOpen(kind, prefix != null ? prefix : `${_ts()} `);
    m.full = text || "";
    m.closed = true;
  }

  // Python pushes chat lines here from backend threads (wake pipeline, team).
  // Albedo answers type out; system/error lines appear instantly.
  window._albedo_chat_push = function (kind, text) {
    if (kind === "albedo") _twMessage("albedo", text, `${_ts()} `);
    else appendLine(kind, text);
  };
  eel.expose(_albedo_chat_push, "_albedo_chat_push");

  // Live token stream from the direct answer path.
  window._albedo_chat_token = function (tok) { _twToken(tok); };
  eel.expose(_albedo_chat_token, "_albedo_chat_token");
  window._albedo_chat_token_end = function () { _twClose(); };
  eel.expose(_albedo_chat_token_end, "_albedo_chat_token_end");

  // Settings panel calls this when the user changes persona from the drawer
  window._albedo_persona_select = function (name) { _applyPersonaName(name); };

  // safety_catch — Python sends an approval request; we show the modal
  window._albedo_approval_request = function(req) {
    const modal    = document.getElementById("approvalModal");
    const cmdEl    = document.getElementById("approvalCmd");
    const reqEl    = document.getElementById("approvalRequester");
    const approveBtn = document.getElementById("approvalApprove");
    const denyBtn    = document.getElementById("approvalDeny");
    if (!modal) return;

    cmdEl.textContent = req.display  || "(unknown command)";
    reqEl.textContent = "requester: " + (req.requester || "swarm");

    function _respond(approved) {
      modal.setAttribute("aria-hidden", "true");
      modal.classList.remove("is-visible");
      try { eel.approve_command(approved)(); } catch { /* ignore */ }
      approveBtn.removeEventListener("click", _onApprove);
      denyBtn.removeEventListener("click",    _onDeny);
    }
    function _onApprove() { _respond(true);  }
    function _onDeny()    { _respond(false); }

    approveBtn.addEventListener("click", _onApprove, { once: true });
    denyBtn.addEventListener("click",    _onDeny,    { once: true });

    modal.removeAttribute("aria-hidden");
    modal.classList.add("is-visible");
  };
  eel.expose(_albedo_approval_request, "_albedo_approval_request");

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
            const qr = await eel.send_chat(r.text, _history.slice(-10))();
            if (qr && qr.ok) {
              if (qr.mode === "team") {
                appendLine("system", "[TEAM activated — see Team window]");
              }
              if (!qr.streamed && qr.mode !== "team") {
                _twMessage("albedo", _personaName + "  " + (qr.answer || "(no response)"),
                           `${_ts()} `);
              }
              if (qr.mode !== "team" && qr.answer) {
                _history.push({ role: "user", content: r.text });
                _history.push({ role: "assistant", content: qr.answer });
              }
            } else {
              _twClose();
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
