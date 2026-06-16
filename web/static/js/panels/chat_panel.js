/**
 * chat_panel.js — CHAT surface: you talk, Albedo decides automatically whether
 * to answer directly or spin up the specialist team (router in agent_team.py).
 * Live team/RAG activity shows up in the Brain + Team visualization windows.
 *
 * Host-agnostic: ChatPanel.mount(rootEl) renders into any container.
 *
 * Backend:
 *   send_chat(text, history)  -> {ok, mode, reason, answer, error}
 *     mode = "direct" | "team"
 */
(function () {
  "use strict";

  function _el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function mount(root) {
    if (!root) return;
    root.innerHTML = "";
    root.classList.add("panel", "panel--chat");

    root.appendChild(_el("div", "panel__title", "▶ CHAT"));

    // Feed
    const feed = _el("div", "panel__chat-feed");
    root.appendChild(feed);

    function append(kind, text) {
      const line = _el("div", `panel__chat-line panel__chat-line--${kind}`, text);
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    }
    append("system", "Ready. Just talk — Albedo will route to a direct answer or the team automatically.");

    // History (last N exchanges sent back as context)
    const history = [];

    // Subscribe to router decisions so the chat shows when team kicks in
    if (window.EventBus) {
      EventBus.on("router.decision", (e) => {
        if (e.mode === "team") {
          append("system", "[TEAM activated — live progress in Team window]");
        }
      });
    }

    // Input row
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
      try {
        const r = await eel.send_chat(text, history.slice(-10))();
        if (!r || !r.ok) {
          append("error", "[ERR] " + (r && r.error || "no response"));
        } else {
          append("albedo", r.answer || "(no answer)");
          history.push({ role: "user", content: text });
          history.push({ role: "assistant", content: r.answer || "" });
        }
      } catch (e) {
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
