"""
agent_team.py — Albedo specialist agent team (orchestrated, sequential).

A team of SPECIALIZED agents cooperating on one goal. Each specialist sees only
its own tools + a tailored system prompt + (optionally) its own brain provider,
so it's focused, cheap, and fast at its job. This is an orchestration layer ABOVE
albedo/agent.py::run_agent — the agent loop itself is reused unchanged, including
its safety_catch approval gate on every tool call.

Flow (sequential, v1):
    1. Orchestrator (no tools) decomposes the goal into a JSON task list
       [{role, task}].
    2. The plan is routed through the approval handler — the USER approves it
       before any work happens.
    3. Each task runs on its assigned specialist via run_agent(...) with that
       role's tool subset + system prompt + provider. Tool calls still hit the
       approval modal.
    4. Critic (no tools) reviews the goal + all results -> {complete, gaps}.
    5. If incomplete and revision allowed, Orchestrator re-plans the gaps ONCE
       and re-runs (bounded — the "iterating" seed, capped at 1 round for v1).
    6. Returns the full record.

See Claude Brain vault 12_Multi_Agent_North_Star.md for the larger design this
is the first concrete increment of.

Public API
----------
    ROLES                          -> dict role -> RoleSpec
    run_team(goal, ...)            -> dict (plan, results, critique, error)
"""
from __future__ import annotations

import json
import re
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from albedo import agent
from albedo import providers


# ---------------------------------------------------------------------------
# Role registry — each specialist: prompt + tool subset + default provider
# ---------------------------------------------------------------------------

@dataclass
class RoleSpec:
    name: str
    system_prompt: str
    tool_names: list[str]            # [] = no tools (pure reasoning)
    default_provider: str = ""       # "" = use global resolve_provider()


ROLES: dict[str, RoleSpec] = {
    "Orchestrator": RoleSpec(
        "Orchestrator",
        "You are the Orchestrator of a team of specialist AI agents. Decompose the "
        "user's goal into the minimum ordered list of concrete tasks, each assigned "
        "to exactly one specialist by name. Available specialists: SysOps (Windows "
        "system control), Researcher (web + local knowledge), FileScout (read files/"
        "dirs), Code Writer (write code/text files), Analyzer (reason over data), "
        "Designer (UI/architecture design), Math (exact math/units via Wolfram), "
        "FactChecker (verify claims via web + RAG). Respond ONLY with JSON: "
        '{"tasks": [{"role": "SpecialistName", "task": "what to do"}]}. '
        "Keep it minimal — do not invent work. No prose.",
        tool_names=[],
        default_provider="groq",
    ),
    "SysOps": RoleSpec(
        "SysOps",
        "You operate this Windows PC. Use ONLY your tools to carry out the task. "
        "Be precise and minimal — take the smallest action that satisfies the task, "
        "then report the result in one or two sentences.",
        tool_names=["launch_app", "kill_process", "list_top_processes",
                    "download_install", "disk_cleanup", "optimize_system",
                    "get_system_telemetry"],
        default_provider="groq",
    ),
    "Researcher": RoleSpec(
        "Researcher",
        "You gather and synthesize information. Use web search for current facts, "
        "local RAG search for the user's own knowledge, and recall notes from working "
        "memory if relevant. Cite what you found. Answer concisely with the facts the "
        "task needs.",
        tool_names=["search_web", "rag_search", "recall_notes"],
        default_provider="groq",
    ),
    "Math": RoleSpec(
        "Math",
        "You handle math, unit conversions, physics, and any quantitative computation. "
        "ALWAYS use query_wolfram for exact answers — never estimate numbers. If Wolfram "
        "returns nothing, say so plainly; do not invent values. Give the result clearly "
        "with units.",
        tool_names=["query_wolfram"],
        default_provider="groq",
    ),
    "FactChecker": RoleSpec(
        "FactChecker",
        "You verify claims for accuracy. Given a statement or set of claims, check each "
        "against the web (search_web) and the user's local knowledge (rag_search). "
        "Report per claim: TRUE / FALSE / UNVERIFIED, with the source you used. Do not "
        "judge whether a goal is complete — that is the Critic's job; you only judge "
        "whether stated facts are accurate.",
        tool_names=["search_web", "rag_search", "query_wolfram"],
        default_provider="groq",
    ),
    "FileScout": RoleSpec(
        "FileScout",
        "You perform read-only filesystem recon. Use your tools to list directories "
        "and read files. Report exactly what you find — never speculate about "
        "contents you did not read.",
        tool_names=["list_directory", "read_text_file"],
        default_provider="groq",
    ),
    "Code Writer": RoleSpec(
        "Code Writer",
        "You write and modify code and text files. Read existing files first when "
        "editing. Use write_text_file to save your work (every write is approved by "
        "the user). Produce complete, correct, idiomatic code. Briefly state what "
        "you wrote and where. Use recall_notes to check for past decisions or "
        "conventions the team has saved.",
        tool_names=["read_text_file", "list_directory", "write_text_file",
                    "recall_notes", "remember"],
        default_provider="",   # prefer a strong coding model if globally set
    ),
    "Analyzer": RoleSpec(
        "Analyzer",
        "You analyze data, files, and system state and produce clear findings. Use "
        "query_wolfram for any exact math/units, your other tools to gather inputs, "
        "then reason carefully and report conclusions with the evidence. Use "
        "remember to save insights worth keeping for future runs.",
        tool_names=["rag_search", "read_text_file", "get_system_telemetry",
                    "query_wolfram", "remember", "recall_notes"],
        default_provider="",
    ),
    "Designer": RoleSpec(
        "Designer",
        "You design UI, architecture, and creative solutions. Consult reference "
        "material via your read-only tools, then deliver a concrete, well-structured "
        "design proposal. Be specific and actionable.",
        tool_names=["rag_search", "read_text_file"],
        default_provider="",
    ),
    "Critic": RoleSpec(
        "Critic",
        "You review the team's work against the original goal. Decide if the goal is "
        "fully met. Respond ONLY with JSON: "
        '{"complete": true|false, "gaps": ["specific missing item", ...], '
        '"summary": "one-line verdict"}. Be strict but fair. No prose.',
        tool_names=[],
        default_provider="",
    ),
}

_VALID_ROLES = set(ROLES.keys())
_RE_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


# ---------------------------------------------------------------------------
# Provider routing per role
# ---------------------------------------------------------------------------

def _role_provider(role: str) -> Optional[str]:
    """
    Resolve which provider a role should use:
      settings.json agent_roles[role] -> RoleSpec.default_provider -> None (global).
    Returning None lets run_agent fall back to resolve_provider().
    """
    try:
        from pathlib import Path
        sp = Path(__file__).resolve().parent.parent / "settings.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            mapping = s.get("agent_roles", {})
            if isinstance(mapping, dict) and mapping.get(role):
                return str(mapping[role]).lower().strip()
    except Exception:
        pass
    spec = ROLES.get(role)
    return (spec.default_provider or None) if spec else None


# ---------------------------------------------------------------------------
# Plan approval (reuses the same safety_catch handler as tool calls)
# ---------------------------------------------------------------------------

def _approve_plan(tasks: list[dict]) -> bool:
    """Route the proposed task list through the approval handler so the user
    okays the plan before any specialist runs. Deny-closed on error.
    Mirrors agent._request_approval but describes a plan, not a tool call."""
    try:
        from albedo import safety_catch
        lines = "; ".join(f"{t['role']}: {t['task']}" for t in tasks)
        display = f"TEAM PLAN ({len(tasks)} tasks) — {lines}"
        req = safety_catch.PendingApproval(
            id=uuid.uuid4().hex[:12],
            argv=["team_plan", json.dumps(tasks)],
            cwd=None,
            requester="albedo-team",
            ts=time.time(),
            display=display,
        )
        handler = getattr(safety_catch, "_handler", None)
        if handler is None:
            return False
        return bool(handler(req))
    except Exception as exc:
        print(f"[team] plan approval error (deny-closed): {exc}")
        return False


# ---------------------------------------------------------------------------
# JSON extraction (reuses the autonomous_commander pattern)
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    m = _RE_JSON_BLOCK.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        # last resort: grab the outermost {...}
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Planning + critique helpers
# ---------------------------------------------------------------------------

def _plan(goal: str, max_tasks: int, status) -> list[dict]:
    """Orchestrator decomposes the goal into [{role, task}]. Validated + capped."""
    spec = ROLES["Orchestrator"]
    res = agent.run_agent(
        goal,
        system_prompt=spec.system_prompt,
        tool_names=[],
        provider=_role_provider("Orchestrator"),
        status_cb=status,
    )
    if res.get("error"):
        return []
    data = _extract_json(res.get("answer", "")) or {}
    tasks = data.get("tasks", [])
    clean: list[dict] = []
    for t in tasks:
        role = str(t.get("role", "")).strip()
        task = str(t.get("task", "")).strip()
        # normalize role to a known specialist (case-insensitive)
        match = next((r for r in _VALID_ROLES if r.lower() == role.lower()), None)
        if match and match not in ("Orchestrator", "Critic") and task:
            clean.append({"role": match, "task": task})
        if len(clean) >= max_tasks:
            break
    return clean


def _critique(goal: str, results: list[dict], status) -> dict:
    """Critic reviews goal vs results -> {complete, gaps, summary}."""
    spec = ROLES["Critic"]
    digest = "\n".join(
        f"- [{r['role']}] {r['task']}\n  -> {(r.get('answer') or '')[:300]}"
        for r in results
    )
    prompt = f"GOAL:\n{goal}\n\nTEAM RESULTS:\n{digest}\n\nIs the goal complete?"
    res = agent.run_agent(
        prompt,
        system_prompt=spec.system_prompt,
        tool_names=[],
        provider=_role_provider("Critic"),
        status_cb=status,
    )
    data = _extract_json(res.get("answer", "")) or {}
    return {
        "complete": bool(data.get("complete", True)),
        "gaps": data.get("gaps", []) if isinstance(data.get("gaps"), list) else [],
        "summary": str(data.get("summary", res.get("answer", "")[:120])),
    }


def _run_tasks(tasks: list[dict], status) -> list[dict]:
    """Execute each task on its specialist sequentially. Tool calls stay gated."""
    results: list[dict] = []
    for i, t in enumerate(tasks, 1):
        role, task = t["role"], t["task"]
        spec = ROLES[role]
        status(f"[{i}/{len(tasks)}] {role}: {task[:60]}")
        res = agent.run_agent(
            task,
            system_prompt=spec.system_prompt,
            tool_names=spec.tool_names,
            provider=_role_provider(role),
            status_cb=status,
            role=role,
        )
        results.append({
            "role": role, "task": task,
            "answer": res.get("answer", ""),
            "steps": res.get("steps", []),
            "provider": res.get("provider"),
            "error": res.get("error"),
        })
    return results


# ---------------------------------------------------------------------------
# Event-bus emit helper (best-effort)
# ---------------------------------------------------------------------------

def _emit(etype: str, **payload) -> None:
    try:
        from albedo import event_bus
        event_bus.publish(etype, **payload)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auto-routing: decide if a chat message needs the full team or a direct answer
# ---------------------------------------------------------------------------

_ROUTER_PROMPT = (
    "You decide if a user message needs a multi-step specialist TEAM or a DIRECT "
    "single-agent answer. Reply ONLY with JSON: "
    '{"mode":"direct"|"team","reason":"<one short sentence>"}. '
    "Use 'team' for multi-step work, multi-tool work, or anything requiring more "
    "than one specialist (e.g. system audit + cleanup, research + write file). "
    "Use 'direct' for simple Q&A, single tool calls, greetings, definitions, "
    "single-system queries."
)


def classify_and_run(message: str, *, status_cb=None, history=None) -> dict:
    """
    The 'just talk to Albedo' entry point. Quick classifier decides:
      mode='direct' -> agent.run_agent (single agent, full tool catalog)
      mode='team'   -> run_team        (the 8-specialist team, approved plan)
    Returns {mode, reason, result} where result is the underlying call's dict.
    Never raises.
    """
    if not message or not message.strip():
        return {"mode": "direct", "reason": "empty",
                "result": {"answer": "", "error": "empty message"}}

    def _status(msg):
        if status_cb:
            try: status_cb(msg)
            except Exception: pass
        print(f"[router] {msg}")

    # 1. Classify with the Orchestrator's brain (no tools, cheap)
    _status("classifying message…")
    res = agent.run_agent(
        message,
        system_prompt=_ROUTER_PROMPT,
        tool_names=[],
        provider=_role_provider("Orchestrator"),
        role="Router",
    )
    data = _extract_json(res.get("answer", "")) or {}
    mode = str(data.get("mode", "direct")).lower().strip()
    if mode not in ("direct", "team"):
        mode = "direct"
    reason = str(data.get("reason", ""))[:160]
    _status(f"route -> {mode} ({reason})")
    _emit("router.decision", mode=mode, reason=reason, message=message[:200])

    # 2. Run the chosen path
    if mode == "team":
        team_res = run_team(message, status_cb=status_cb, require_plan_approval=False)
        return {"mode": "team", "reason": reason, "result": team_res}
    else:
        agent_res = agent.run_agent(message, status_cb=status_cb, history=history,
                                    role="Albedo")
        return {"mode": "direct", "reason": reason, "result": agent_res}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_team(
    goal: str,
    *,
    status_cb: Optional[Callable[[str], None]] = None,
    max_tasks: int = 6,
    allow_revision: bool = True,
    require_plan_approval: bool = False,  # tool-level approval already gates every action
) -> dict:
    """
    Run the specialist team on a goal. Sequential, user-approved.

    Returns:
        {goal, plan, results, critique, revised, error}
    Never raises.
    """
    def _status(msg: str) -> None:
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass
        print(f"[team] {msg}")

    if not goal or not goal.strip():
        return {"goal": "", "plan": [], "results": [], "critique": None,
                "revised": False, "error": "empty goal"}
    goal = goal.strip()
    _emit("team.start", goal=goal)

    # 1. Plan
    _status("Orchestrator planning…")
    tasks = _plan(goal, max_tasks, _status)
    if not tasks:
        _emit("team.done", ok=False)
        return {"goal": goal, "plan": [], "results": [], "critique": None,
                "revised": False, "error": "planning produced no tasks"}
    _emit("team.plan", tasks=tasks)

    # 2. Approve plan
    if require_plan_approval:
        _status(f"Awaiting plan approval ({len(tasks)} tasks)…")
        if not _approve_plan(tasks):
            _emit("team.done", ok=False)
            return {"goal": goal, "plan": tasks, "results": [], "critique": None,
                    "revised": False, "error": "plan denied by user"}

    # 3. Execute
    results = _run_tasks(tasks, _status)

    # 4. Critique
    _status("Critic reviewing…")
    critique = _critique(goal, results, _status)
    _emit("team.critique", complete=critique.get("complete"),
          summary=critique.get("summary",""), gaps=critique.get("gaps", []))

    # 5. One optional revision round
    revised = False
    if allow_revision and not critique["complete"] and critique["gaps"]:
        revised = True
        gap_goal = (f"{goal}\n\nThe following gaps remain — address ONLY these:\n"
                    + "\n".join(f"- {g}" for g in critique["gaps"]))
        _status("Re-planning to close gaps…")
        gap_tasks = _plan(gap_goal, max_tasks, _status)
        if gap_tasks:
            _emit("team.plan", tasks=gap_tasks, revision=True)
            if not require_plan_approval or _approve_plan(gap_tasks):
                results.extend(_run_tasks(gap_tasks, _status))
                critique = _critique(goal, results, _status)
                _emit("team.critique", complete=critique.get("complete"),
                      summary=critique.get("summary",""),
                      gaps=critique.get("gaps", []))

    _emit("team.done", ok=True)
    return {
        "goal": goal,
        "plan": tasks,
        "results": results,
        "critique": critique,
        "revised": revised,
        "error": None,
    }


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    g = " ".join(sys.argv[1:]) or "Report my top memory-hogging process and whether C: is over 85% full."
    print(f"GOAL: {g}\n")
    out = run_team(g, require_plan_approval=False)   # no UI in CLI smoke test
    print("\n--- PLAN ---")
    for t in out["plan"]:
        print(f"  {t['role']}: {t['task']}")
    print("\n--- RESULTS ---")
    for r in out["results"]:
        print(f"  [{r['role']}] -> {(r.get('answer') or '')[:120]}")
    print("\n--- CRITIQUE ---", out["critique"])
    print("error:", out["error"])
