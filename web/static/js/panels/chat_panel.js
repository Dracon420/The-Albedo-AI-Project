/**
 * chat_panel.js — CHAT surface: you talk, Albedo decides automatically whether
 * to answer directly or spin up the specialist team (router in agent_team.py).
 * Live team/RAG activity shows up in the Brain + Team visualization windows.
 *
 * Host-agnostic: ChatPanel.mount(rootEl) renders into any container.
 *
 * Answers reveal at a steady reading pace via a typewriter queue — both live
 * streamed tokens and full pushed messages (team results) flow through it.
 */
(function () {
  "use strict";

  let _feed = null;       // current panel feed element
  let _pendingEl = null;  // "thinking" indicator
  let _anim = null;       // thinking-dots interval

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function _clearPending() {
    if (_anim) { clearInterval(_anim); _anim = null; }
    if (_pendingEl) { _pendingEl.remove(); _pendingEl = null; }
  }

  // ── Typewriter queue (reading-pace reveal) ────────────────────────────────
  const _tw = { q: [], timer: null, STEP_MS: 18 };
  function _twPump() {
    if (_tw.timer || !_feed) return;
    _tw.timer = setInterval(() => {
      const m = _tw.q[0];
      if (!m) { clearInterval(_tw.timer); _tw.timer = null; return; }
      if (!m.el) {
        m.el = _el("div", `panel__chat-line panel__chat-line--${m.kind}`, "");
        _feed.appendChild(m.el);
      }
      const remaining = m.full.length - m.shown;
      if (remaining > 0) {
        const step = Math.min(remaining, Math.max(1, Math.ceil(remaining / 22)));
        m.shown += step;
        m.el.textContent = m.full.slice(0, m.shown);
        _feed.scrollTop = _feed.scrollHeight;
      } else if (m.closed) {
        _tw.q.shift();
      }
    }, _tw.STEP_MS);
  }
  function _twOpen(kind) {
    const m = { kind, full: "", shown: 0, closed: false, el: null };
    _tw.q.push(m);
    _twPump();
    return m;
  }
  function _twToken(tok) {
    _clearPending();
    let m = _tw.q[_tw.q.length - 1];
    if (!m || m.closed) m = _twOpen("albedo");
    m.full += tok;
    _twPump();
  }
  function _twClose() {
    const m = _tw.q[_tw.q.length - 1];
    if (m) m.closed = true;
  }
  function _twMessage(kind, text) {
    _clearPending();
    const m = _twOpen(kind);
    m.full = text || "";
    m.closed = true;
  }

  if (typeof eel !== "undefined") {
    window._albedo_chat_token = function (tok) { _twToken(tok); };
    eel.expose(_albedo_chat_token, "_albedo_chat_token");
    window._albedo_chat_token_end = function () { _twClose(); };
    eel.expose(_albedo_chat_token_end, "_albedo_chat_token_end");
    // Team per-agent results + wake pipeline lines push here.
    window._albedo_chat_push = function (kind, text) {
      if (kind === "albedo") _twMessage("albedo", text);
      else if (_feed) {
        const line = _el("div", `panel__chat-line panel__chat-line--${kind}`, text);
        _feed.appendChild(line);
        _feed.scrollTop = _feed.scrollHeight;
      }
    };
    eel.expose(_albedo_chat_push, "_albedo_chat_push");
  }

  function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("panel", "panel--chat");

    root.appendChild(_el("div", "panel__title", "▶ CHAT"));

    const feed = _el("div", "panel__chat-feed");
    root.appendChild(feed);
    _feed = feed;

    function append(kind, text) {
      const line = _el("div", `panel__chat-line panel__chat-line--${kind}`, text);
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    }
    append("system", "Ready. Just talk — Albedo will route to a direct answer or the team automatically.");

    const history = [];

    if (window.EventBus) {
      EventBus.on("router.decision", (e) => {
        if (e.mode === "team") {
          append("system", "[TEAM activated — live progress in Team window]");
        }
      });
    }

    const row = _el("div", "panel__chat-input-row");
    const input = _el("input", "panel__input");
    input.type = "text";
    input.placeholder = "Say anything…";
    const sendBtn = _el("button", "cmd-btn cmd-btn--accent", "SEND");
    row.appendChild(input);
    row.appendChild(sendBtn);
    root.appendChild(row);

    async function send() {
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      append("user", "> " + text);
      sendBtn.disabled = true;

      const pending = _el("div", "panel__chat-line panel__chat-line--system", "Albedo is thinking");
      feed.appendChild(pending);
      feed.scrollTop = feed.scrollHeight;
      let dots = 0;
      _pendingEl = pending;
      _anim = setInterval(() => {
        dots = (dots + 1) % 4;
        pending.textContent = "Albedo is thinking" + ".".repeat(dots);
      }, 400);

      try {
        const r = await eel.send_chat(text, history.slice(-10))();
        _clearPending();
        if (!r || !r.ok) {
          _twClose();
          append("error", "[ERR] " + (r && r.error || "no response"));
        } else {
          // Streamed answers are already typing; team results stream via
          // _albedo_chat_push. Only type a full direct answer here.
          if (!r.streamed && r.mode !== "team") {
            _twMessage("albedo", r.answer || "(no answer)");
          }
          history.push({ role: "user", content: text });
          history.push({ role: "assistant", content: r.answer || "" });
        }
      } catch (e) {
        _clearPending();
        _twClose();
        append("error", "[EXC] " + e);
      } finally {
        sendBtn.disabled = false;
        input.focus();
      }
    }

    sendBtn.addEventListener("click", send);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

    setTimeout(() => input.focus(), 100);
  }

  window.ChatPanel = { mount };
})();
