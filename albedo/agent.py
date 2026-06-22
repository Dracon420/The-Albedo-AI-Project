"""
agent.py — Albedo agentic loop (plan → act → observe).

Drives a user-selected LLM brain (via providers.complete_with_tools) over the
tool catalog (agent_tools) in an iterative loop:

    1. Send conversation + tool catalog to the brain.
    2. If the brain returns tool calls:
         - For each call, gate it through approval policy (safety_catch handler).
         - Execute approved calls via agent_tools.run_tool; record results.
         - Append the assistant turn + tool results to the conversation.
         - Loop.
       If the brain returns only text: that's the final answer — return it.
    3. Stop after MAX_ITERATIONS to prevent runaway loops.

Approval policy (user setting, default = "approve everything")
-------------------------------------------------------------
settings.json "agent_autonomy" ∈ {
    "approve_all"        : every tool call needs approval (default — safest)
    "approve_destructive": only destructive tools need approval
    "full_auto"          : no approval (fastest, riskiest)
}
Approval is requested through the SAME safety_catch handler the rest of the app
uses (set_approval_handler in app.py wires it to the Eel modal), so agent tool
approvals appear in the HUD, not the console.

Public API
----------
    run_agent(user_message, *, history=None, system_prompt=None,
              provider=None, model=None, status_cb=None) -> dict
        {answer, steps:[...], provider, model, iterations, error}

Never raises — failures come back in the result dict.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Callable, Optional

from albedo import agent_tools
from albedo import providers

MAX_ITERATIONS = 4  # hard cap on plan->act->observe cycles per user message
                    # (low — the name-based loop-breaker ends repeats sooner;
                    #  bounds worst-case latency for the interactive chat)

_DEFAULT_SYSTEM = (
    "You are Albedo (Cortana persona): a sharp, efficient, lightly witty "
    "Spartan-class AI. Address the user as 'Chief'. Talk like a person, not a "
    "manual — terse and natural.\n"
    "STYLE — this is how you avoid sounding clunky:\n"
    "- Default to 1-3 sentences. Use a numbered/bulleted list ONLY when the user "
    "explicitly asks for steps or options.\n"
    "- After a tool runs, its results already show in the UI. Give ONE short "
    "takeaway or just confirm — NEVER describe the output ('these results show "
    "the installed applications…', 'the list includes name, memory, CPU…'). That "
    "narration is the main thing that makes you sound robotic.\n"
    "- Make at most ONE brief offer of a next step, and never re-list what you "
    "already did.\n"
    "- If the user declines ('no', 'nope', 'nah', 'never mind', 'not now', 'no "
    "thanks'): reply with a single short acknowledgement (e.g. 'Understood, "
    "Chief.') and STOP. No summary, no new offer, no recap of what you've done.\n"
    "BEHAVIOR:\n"
    "1. Advice questions ('how can I…', 'should I…', 'what is…') → answer "
    "directly. Don't run system-changing tools; you may OFFER one and ask first.\n"
    "2. SEE/LIST/SHOW/CHECK/FIND requests ('list installed apps', 'list "
    "processes') → immediately call the matching read-only tool; never ask "
    "permission to read, never just say you 'can'.\n"
    "3. Tools that delete/clean/kill/install/uninstall/change settings → describe "
    "and confirm first, even with permission.\n"
    "4. Follow-ups: 'yes'/'do it'/an item name continues the prior thread and "
    "acts; a decline ends it (see STYLE). Never say you don't know what they mean.\n"
    "Don't narrate tool use. NEVER write tool/function-call syntax in your reply "
    "(no <function=...>, <tool_call>, or JSON tool blocks) — either call the tool "
    "for real or just say it in plain words."
)


# Models occasionally emit a tool call as literal TEXT (e.g. Llama's
# "<function=remember{...}></function>") instead of a structured tool_call, which
# then leaks into the chat. Strip any such markup from the final answer.
_TOOL_MARKUP_BLOCK = re.compile(
    r"<\s*(function|tool_call|invoke|tool_code)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.S | re.I,
)
_TOOL_MARKUP_TAG = re.compile(
    r"<\s*/?\s*(function|tool_call|invoke|tool_code)\b[^>]*>",
    re.I,
)


def _strip_tool_markup(text: str) -> str:
    if not text or "<" not in text:
        return text
    text = _TOOL_MARKUP_BLOCK.sub("", text)
    text = _TOOL_MARKUP_TAG.sub("", text)
    # tidy the gaps left behind ("I can  so I can…" -> "I can so I can…")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Autonomy / approval policy
# ---------------------------------------------------------------------------

def _autonomy_mode() -> str:
    """Read agent_autonomy from settings.json. Default 'approve_all'."""
    try:
        from pathlib import Path
        sp = Path(__file__).resolve().parent.parent / "settings.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            mode = str(s.get("agent_autonomy", "")).strip().lower()
            if mode in ("approve_all", "approve_destructive", "full_auto"):
                return mode
    except Exception:
        pass
    return "approve_all"


def _needs_approval(tool_name: str, mode: str) -> bool:
    if mode == "full_auto":
        return False
    spec = agent_tools.get_tool(tool_name)
    destructive = bool(spec and spec.destructive)
    if mode == "approve_destructive":
        return destructive
    # approve_all (default)
    return True


def _request_approval(tool_name: str, arguments: dict) -> bool:
    """
    Ask the registered safety_catch handler to approve a tool call. Reuses the
    same handler the Eel UI wired (set_approval_handler), so it surfaces in the
    HUD modal. Falls back to deny-closed if anything goes wrong.
    """
    try:
        from albedo import safety_catch
        # Build a PendingApproval that describes the tool call (not a subprocess).
        arg_str = ", ".join(f"{k}={v!r}" for k, v in (arguments or {}).items())
        display = f"{tool_name}({arg_str})"
        req = safety_catch.PendingApproval(
            id=uuid.uuid4().hex[:12],
            argv=[tool_name, json.dumps(arguments or {})],
            cwd=None,
            requester="albedo-agent",
            ts=time.time(),
            display=display,
        )
        handler = getattr(safety_catch, "_handler", None)
        if handler is None:
            return False
        return bool(handler(req))
    except Exception as exc:
        print(f"[agent] approval error (deny-closed): {exc}")
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_agent(
    user_message: str,
    *,
    history: Optional[list[dict]] = None,
    system_prompt: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    tool_names: Optional[list[str]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    on_token: Optional[Callable[[str], None]] = None,
    role: str = "agent",
) -> dict:
    """
    Run the agentic loop for one user message. Returns a result dict:
        {answer, steps, provider, model, iterations, error}
    `steps` is a list of {type, ...} entries describing what happened
    (tool_call, tool_result, denied, final) for UI/debugging.

    tool_names: restrict the tool catalog this agent sees to just these tools
    (specialist focus — fewer tokens, faster, less mis-selection). When None,
    the agent sees ALL tools (backward compatible). An empty list [] means the
    agent gets NO tools (pure reasoning role, e.g. Orchestrator/Critic).
    Never raises.
    """
    def _status(msg: str) -> None:
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass
        print(f"[agent] {msg}")

    if not user_message or not user_message.strip():
        return {"answer": "", "steps": [], "provider": None, "model": None,
                "iterations": 0, "error": "empty message"}

    mode = _autonomy_mode()
    # None -> all tools (back-compat); [] -> no tools; [names] -> just those.
    tools = agent_tools.get_tool_schemas(tool_names)

    # Best-effort live event emission to the Brain/Team visualizations.
    def _emit(etype: str, **payload) -> None:
        try:
            from albedo import event_bus
            event_bus.publish(etype, **payload)
        except Exception:
            pass

    _emit("agent.state", role=role, state="thinking", task=user_message.strip())

    # Build initial conversation
    messages: list[dict] = [{"role": "system", "content": system_prompt or _DEFAULT_SYSTEM}]
    if history:
        for h in history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message.strip()})

    steps: list[dict] = []
    used_provider = providers.resolve_provider(provider)
    used_model = providers.resolve_model(used_provider, model)
    _executed: set[str] = set()   # tool NAMES already run this turn

    for iteration in range(1, MAX_ITERATIONS + 1):
        _status(f"thinking (iteration {iteration}/{MAX_ITERATIONS}) via {used_provider}:{used_model}")
        result = _complete_with_retry(messages, tools, provider, model, _status,
                                      on_token=on_token)
        used_provider = result.get("provider") or used_provider
        used_model = result.get("model") or used_model

        if result.get("error"):
            _emit("agent.state", role=role, state="error", task=user_message.strip())
            return {"answer": "", "steps": steps, "provider": used_provider,
                    "model": used_model, "iterations": iteration,
                    "error": result["error"]}

        tool_calls = result.get("tool_calls") or []

        # No tool calls -> final answer.
        if not tool_calls:
            answer = _strip_tool_markup(result.get("text", "") or "")
            steps.append({"type": "final", "text": answer})
            _emit("agent.state", role=role, state="done", task=user_message.strip())
            return {"answer": answer, "steps": steps, "provider": used_provider,
                    "model": used_model, "iterations": iteration, "error": None}

        # Loop-breaker: some models (groq) keep re-requesting a tool they already
        # ran (often with slightly different args) instead of answering. Match on
        # tool NAME — if every requested call is to an already-run tool, the data
        # is in hand, so force a FINAL answer with NO tools instead of looping to
        # the iteration cap (the 150s hang).
        if tool_calls and all(tc.name in _executed for tc in tool_calls):
            _status("data already gathered — composing answer")
            final = _complete_with_retry(messages, [], provider, model, _status)
            answer = _strip_tool_markup(final.get("text", "") or "")
            steps.append({"type": "final", "text": answer})
            _emit("agent.state", role=role, state="done", task=user_message.strip())
            return {"answer": answer, "steps": steps,
                    "provider": final.get("provider") or used_provider,
                    "model": final.get("model") or used_model,
                    "iterations": iteration, "error": None}

        # Record the assistant turn (with its tool calls) into history.
        messages.append(_assistant_turn(result))

        # Execute each requested tool call.
        for tc in tool_calls:
            steps.append({"type": "tool_call", "name": tc.name, "arguments": tc.arguments})
            _status(f"tool call: {tc.name}({tc.arguments})")
            _emit("agent.state", role=role, state="tool", task=tc.name)
            _emit("tool.call", role=role, name=tc.name, args=dict(tc.arguments or {}))

            if _needs_approval(tc.name, mode):
                _status(f"awaiting approval for {tc.name}…")
                approved = _request_approval(tc.name, tc.arguments)
                if not approved:
                    denial = f"User denied execution of {tc.name}."
                    steps.append({"type": "denied", "name": tc.name})
                    messages.append(_tool_result_turn(tc, denial))
                    _status(f"denied: {tc.name}")
                    _emit("tool.result", role=role, name=tc.name, ok=False,
                          summary="denied by user")
                    continue

            output = agent_tools.run_tool(tc.name, tc.arguments)
            _executed.add(tc.name)
            steps.append({"type": "tool_result", "name": tc.name,
                          "output": output[:500]})
            _emit("tool.result", role=role, name=tc.name,
                  ok=not output.startswith("[tool error]"),
                  summary=output[:160].splitlines()[0] if output else "")
            messages.append(_tool_result_turn(tc, output))

    # Hit the iteration cap without a final text answer.
    return {"answer": "I reached my action limit before finishing. Please refine "
                      "the request or break it into smaller steps.",
            "steps": steps, "provider": used_provider, "model": used_model,
            "iterations": MAX_ITERATIONS, "error": "max_iterations"}


# ---------------------------------------------------------------------------
# Provider call with transient-error retry (rate limits, 429, timeouts)
# ---------------------------------------------------------------------------

_TRANSIENT_MARKERS = ("rate", "429", "timeout", "timed out", "503",
                      "overloaded", "temporarily", "try again")


def _is_transient(error: str) -> bool:
    e = (error or "").lower()
    return any(m in e for m in _TRANSIENT_MARKERS)


def _call_with_timeout(messages, tools, provider, model, secs: int = 75,
                       on_token=None) -> dict:
    """Run providers.complete_with_tools in a thread; return error dict on timeout."""
    bucket: dict = {}

    def _go():
        bucket["v"] = providers.complete_with_tools(
            messages, tools=tools, provider=provider, model=model,
            on_token=on_token,
        )

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join(secs)
    if t.is_alive():
        return {"error": f"provider call timed out after {secs}s",
                "text": "", "tool_calls": []}
    return bucket.get("v") or {"error": "no result", "text": "", "tool_calls": []}


def _complete_with_retry(messages, tools, provider, model, status,
                         max_retries: int = 1, call_timeout: int = 75,
                         on_token=None) -> dict:
    """Call the provider; retry briefly on transient errors with backoff.
    complete_with_tools already fails over across providers, so one retry is a
    light backstop — not the 2-3 that compounded into the old 150s hang."""
    delay = 3.0
    result = _call_with_timeout(messages, tools, provider, model, call_timeout,
                                on_token=on_token)
    attempt = 0
    while result.get("error") and _is_transient(result["error"]) and attempt < max_retries:
        attempt += 1
        status(f"transient error ({result['error'][:50]}…) — retry {attempt}/{max_retries} in {delay:.0f}s")
        time.sleep(delay)
        delay *= 2
        result = _call_with_timeout(messages, tools, provider, model, call_timeout,
                                    on_token=on_token)
    return result


# ---------------------------------------------------------------------------
# Conversation-turn builders (neutral shape consumed by providers.py)
# ---------------------------------------------------------------------------

def _assistant_turn(result: dict) -> dict:
    """Build the neutral assistant message (text + tool_calls) for history."""
    return {
        "role": "assistant",
        "content": result.get("text", "") or "",
        "tool_calls": result.get("tool_calls", []),
    }


def _tool_result_turn(tool_call, output: str) -> dict:
    """Build the neutral tool-result message for history."""
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": output,
    }


if __name__ == "__main__":
    # Manual smoke test (requires a configured provider with a key).
    import sys
    msg = " ".join(sys.argv[1:]) or "What is my current CPU and RAM usage?"
    print(f"USER: {msg}\n")
    res = run_agent(msg)
    print("\n--- RESULT ---")
    print("provider :", res["provider"], "| model:", res["model"])
    print("iterations:", res["iterations"], "| error:", res["error"])
    print("steps:")
    for s in res["steps"]:
        print("  ", s.get("type"), s.get("name", ""), str(s.get("arguments", ""))[:60])
    print("\nANSWER:", res["answer"])
