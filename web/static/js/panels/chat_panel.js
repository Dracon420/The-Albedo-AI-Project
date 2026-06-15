/**
 * chat_panel.js — CHAT surface: text in, agent or team response out.
 *
 * Host-agnostic: ChatPanel.mount(rootEl) renders into any container.
 * Lightweight by design — the main Mission Control chat (chat.js) keeps its
 * voice/MIC/wake-word features; this panel is the focused text-driven entry
 * point that can route to the single-agent loop OR the multi-agent team.
 *
 * Backend:
 *   run_agent_query(text)  -> {ok, answer, steps, error}
 *   run_team_query(goal)   -> {ok, plan, results, critique, error}
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

    // Mode toggle: Agent (single) vs Team (multi)
    const modeWrap = _el("div", "panel__mode");
    const agentBtn = _el("button", "cmd-btn panel__mode-btn is-active", "AGENT");
    const teamBtn  = _el("button", "cmd-btn panel__mode-btn", "TEAM");
    modeWrap.appendChild(agentBtn);
    modeWrap.appendChild(teamBtn);
    root.appendChild(modeWrap);
    let mode = "agent";
    agentBtn.addEventListener("click", () => {
      mode = "agent";
      agentBtn.classList.add("is-active");
      teamBtn.classList.remove("is-active");
    });
    teamBtn.addEventListener("click", () => {
      mode = "team";
      teamBtn.classList.add("is-active");
      agentBtn.classList.remove("is-active");
    });

    // Feed
    const feed = _el("div", "panel__chat-feed");
    root.appendChild(feed);

    function append(kind, text) {
      const line = _el("div", `panel__chat-line panel__chat-line--${kind}`, text);
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    }
    append("system", "Ready. AGENT = one tool-using agent; TEAM = the 8-specialist team.");

    // Input row
    const row = _el("div", "panel__chat-input-row");
    const input = _el("input", "panel__input");
    input.type = "text";
    input.placeholder = "Type a message or a goal…";
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
        if (mode === "agent") {
          const r = await eel.run_agent_query(text)();
          if (!r || !r.ok) {
            append("error", "[ERR] " + (r && r.error || "no response"));
          } else {
            append("albedo", r.answer || "(no answer)");
          }
        } else {
          append("system", "[TEAM] orchestrating… (you'll be asked to approve the plan)");
          const r = await eel.run_team_query(text)();
          if (!r || !r.ok) {
            append("error", "[ERR] " + (r && r.error || "no response"));
          } else {
            (r.results || []).forEach((res) => {
              append("albedo", `[${res.role}] ${(res.answer || "").trim()}`);
            });
            const c = r.critique || {};
            append("system",
              `[CRITIC] ${c.complete ? "complete" : "incomplete"} — ${c.summary || ""}`);
          }
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
