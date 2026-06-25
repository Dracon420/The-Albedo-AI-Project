"""
providers.py — Albedo unified LLM provider layer with tool-calling.

The provider-agnostic brain interface for the agent (albedo/agent.py). One
function — complete_with_tools() — dispatches to whichever provider the user
selected, normalizing each SDK's wildly different tool-call format into ONE
internal shape so agent.py never has to care which brain is active.

Locked design decisions (see Claude Brain 11_Agent_Architecture_Plan.md):
  - Brain is user-choosable. No provider privileged. Each user supplies own key.
  - Providers: anthropic | openai | azure | gemini | groq | ollama
  - OpenAI + Azure OpenAI + Groq + Ollama all speak the OpenAI tool-call format,
    so they share ONE adapter (different client constructors / base URLs).
    Anthropic (tool_use blocks) and Gemini (function_call) get bespoke adapters.

Internal normalized shapes
--------------------------
Messages (provider-neutral, what agent.py passes/receives):
    {"role": "system"|"user"|"assistant"|"tool", "content": str,
     "tool_calls": [ToolCall]?,        # on assistant turns
     "tool_call_id": str?, "name": str?}  # on tool-result turns

ToolCall (what the model decided to invoke):
    {"id": str, "name": str, "arguments": dict}

complete_with_tools(messages, tools, provider=None, model=None) -> dict:
    {"text": str,                 # assistant text (may be "")
     "tool_calls": [ToolCall],    # empty list if the model is done
     "raw_assistant_msg": ...,    # provider-native assistant msg, for history
     "provider": str, "model": str, "error": str|None}

Tools come from agent_tools.get_tool_schemas() — provider-neutral
{name, description, parameters:{type,properties,required}}.

Everything degrades gracefully: a missing key/SDK yields error=... not an
exception, so agent.py can surface a readable message or fall through.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Default models per provider (overridable via settings.json / .env / arg)
# ---------------------------------------------------------------------------

DEFAULT_MODELS = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai":    "gpt-4o-mini",
    "azure":     "",          # uses AZURE_OPENAI_DEPLOYMENT
    "gemini":    "gemini-2.0-flash",
    "groq":      "llama-3.3-70b-versatile",
    "ollama":    "albedo-cortana-8b",
}

# Curated, known-good model ids per provider for the BRAIN model dropdown so
# users don't have to memorise provider model strings. The DEFAULT_MODELS pick
# is surfaced first by the UI; a "Custom…" option still lets power users type
# any id. Keep these conservative (stable, currently-served models only).
PROVIDER_MODELS = {
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ],
    "gemini": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ],
    "ollama": [
        "albedo-cortana-8b",
        "albedo-jarvis-8b",
        "albedo-cortana",
        "albedo-jarvis",
    ],
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
    ],
    "azure": [],   # model is the Azure deployment name — not selectable here
}

# Order matters for auto-failover: free cloud providers (gemini, groq) are tried
# before slow local ollama, so a groq rate-limit fails over to fast cloud instead
# of grinding on the 6GB GPU. (Together was removed — its free tier ran out of
# credits and dumped 402s into chat; Gemini + Ollama cover the same fallback.)
PROVIDERS = ("anthropic", "openai", "azure", "gemini", "groq", "ollama")

# Azure tool-calling needs a recent API version; bump 2024-02-01 default.
_AZURE_TOOLS_API_VERSION = "2024-08-01-preview"


# ---------------------------------------------------------------------------
# Internal data shapes
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)

    def __post_init__(self):
        # Models may emit null / non-dict args for zero-parameter tools.
        # Normalize to {} so downstream json.dumps never produces "null"
        # (which OpenAI-format providers like Groq reject as invalid args).
        if not isinstance(self.arguments, dict):
            self.arguments = {}


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _provider_has_key(provider: str) -> bool:
    if provider == "anthropic":
        return bool(_env("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(_env("OPENAI_API_KEY"))
    if provider == "azure":
        return bool(_env("AZURE_OPENAI_KEY") and _env("AZURE_OPENAI_ENDPOINT"))
    if provider == "gemini":
        return bool(_env("GEMINI_API_KEY"))
    if provider == "groq":
        return bool(_env("GROQ_API_KEY"))
    if provider == "ollama":
        return True  # local, no key
    return False


def resolve_provider(provider: str | None = None) -> str:
    """
    Pick the active provider. Priority:
      1. explicit arg
      2. settings.json "brain_provider"
      3. BRAIN_PROVIDER env
      4. first provider (in PROVIDERS order) that has a configured key
      5. "ollama" (always available, offline fallback)
    """
    if provider:
        return provider.lower().strip()
    # settings.json
    try:
        from pathlib import Path
        sp = Path(__file__).resolve().parent.parent / "settings.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            if s.get("brain_provider"):
                return str(s["brain_provider"]).lower().strip()
    except Exception:
        pass
    env_p = _env("BRAIN_PROVIDER").lower()
    if env_p:
        return env_p
    for p in PROVIDERS:
        if p != "ollama" and _provider_has_key(p):
            return p
    return "ollama"


def resolve_model(provider: str, model: str | None = None) -> str:
    if model:
        return model
    # settings.json `brain_model` is ONLY valid for the provider it was set for
    # (`brain_provider`). When the active provider differs (e.g. user picks
    # Azure but brain_model was last saved for Gemini), use the target provider's
    # own default instead — otherwise we'd ship a model name that doesn't exist
    # on the target (-> DeploymentNotFound on Azure, model_not_found on OpenAI).
    try:
        from pathlib import Path
        sp = Path(__file__).resolve().parent.parent / "settings.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            bp = str(s.get("brain_provider", "")).lower().strip()
            bm = str(s.get("brain_model", "")).strip()
            if bm and (not bp or bp == provider):
                return bm
    except Exception:
        pass
    if provider == "azure":
        return _env("AZURE_OPENAI_DEPLOYMENT") or "gpt-35-turbo"
    env_m = _env("BRAIN_MODEL")
    if env_m:
        return env_m
    return DEFAULT_MODELS.get(provider, "")


def available_providers() -> dict[str, bool]:
    """Map provider -> whether it's usable right now (key present)."""
    return {p: _provider_has_key(p) for p in PROVIDERS}


# ---------------------------------------------------------------------------
# Schema translation: neutral -> provider-specific tool format
# ---------------------------------------------------------------------------

def _tools_openai_format(tools: list[dict]) -> list[dict]:
    """OpenAI/Azure/Groq/Ollama: [{type:function, function:{name,description,parameters}}]"""
    return [{"type": "function", "function": t} for t in tools]


def _tools_anthropic_format(tools: list[dict]) -> list[dict]:
    """Anthropic: [{name, description, input_schema}]"""
    return [{
        "name": t["name"],
        "description": t.get("description", ""),
        "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
    } for t in tools]


def _tools_gemini_format(tools: list[dict]):
    """Gemini: a single Tool with function_declarations."""
    from google.genai import types
    decls = []
    for t in tools:
        decls.append(types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("parameters", {"type": "object", "properties": {}}),
        ))
    return [types.Tool(function_declarations=decls)]


# ---------------------------------------------------------------------------
# OpenAI-format adapter (shared: openai, azure, groq, ollama)
# ---------------------------------------------------------------------------

def _msgs_to_openai(messages: list[dict]) -> list[dict]:
    """Convert neutral messages to OpenAI chat format."""
    out: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            })
        elif role == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                } for tc in m["tool_calls"]],
            })
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _openai_client(provider: str):
    """Construct the right client for an OpenAI-format provider.

    timeout=30 + max_retries=0: a hung request raises after 30s with NO internal
    SDK retries (the SDK default is 2, which would turn a hang into 30s*3=90s
    before our own failover ever runs). Our complete_with_tools handles failover.
    """
    common = {"timeout": 30.0, "max_retries": 0}
    if provider == "openai":
        from openai import OpenAI
        return OpenAI(api_key=_env("OPENAI_API_KEY"), **common)
    if provider == "azure":
        from openai import AzureOpenAI
        ver = _env("AZURE_OPENAI_API_VERSION") or _AZURE_TOOLS_API_VERSION
        return AzureOpenAI(
            api_key=_env("AZURE_OPENAI_KEY"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            api_version=ver, **common,
        )
    if provider == "groq":
        from openai import OpenAI
        return OpenAI(api_key=_env("GROQ_API_KEY"),
                      base_url="https://api.groq.com/openai/v1", **common)
    if provider == "ollama":
        from openai import OpenAI
        base = (_env("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        # local model can be slower to first-token; give it more headroom.
        return OpenAI(api_key="ollama", base_url=f"{base}/v1",
                      timeout=90.0, max_retries=0)
    raise ValueError(f"not an OpenAI-format provider: {provider}")


def _complete_openai(provider: str, model: str, messages: list[dict],
                     tools: list[dict], on_token=None) -> dict:
    client = _openai_client(provider)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": _msgs_to_openai(messages),
        # Hard per-request timeout so a hung call raises (→ failover) instead of
        # blocking forever. A chat completion never legitimately needs this long.
        "timeout": 30,
    }
    if tools:
        kwargs["tools"] = _tools_openai_format(tools)
        kwargs["tool_choice"] = "auto"

    # ── Non-streaming path ──────────────────────────────────────────────────
    # IMPORTANT: streaming + tools is broken on Groq (and some others) — it
    # returns EMPTY content, which made the agent loop until the 150s timeout.
    # So only stream when there are NO tools; with tools, use non-streaming.
    # (The client-side typewriter still reveals the answer at reading pace.)
    if on_token is None or tools:
        def _once(kw: dict):
            resp = client.chat.completions.create(**kw)
            choice = resp.choices[0].message
            tcs: list[ToolCall] = []
            for tc in (choice.tool_calls or []):
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                tcs.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
            return (choice.content or ""), tcs

        try:
            text, tool_calls = _once(kwargs)
        except Exception:
            text, tool_calls = "", []
        # Groq function-calling is flaky on tool-result follow-ups: it can return
        # EMPTY content (no text, no tool call) or a 400. The tools already ran,
        # so retry WITHOUT the tool catalog to force a plain text summary.
        if tools and not text and not tool_calls:
            kw2 = dict(kwargs)
            kw2.pop("tools", None)
            kw2.pop("tool_choice", None)
            text, tool_calls = _once(kw2)
        return {
            "text": text,
            "tool_calls": tool_calls,
            "raw_assistant_msg": {"role": "assistant", "content": text,
                                  "tool_calls": tool_calls},
            "provider": provider, "model": model, "error": None,
        }

    # ── Streaming path: fire on_token per text delta, accumulate tool deltas ─
    kwargs["stream"] = True
    text_parts: list[str] = []
    tool_acc: dict[int, dict] = {}   # index -> {id, name, args}
    for chunk in client.chat.completions.create(**kwargs):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            text_parts.append(piece)
            try:
                on_token(piece)
            except Exception:
                pass
        for tc in (getattr(delta, "tool_calls", None) or []):
            slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if tc.id:
                slot["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["args"] += fn.arguments

    text = "".join(text_parts)
    tool_calls = []
    for idx in sorted(tool_acc):
        slot = tool_acc[idx]
        try:
            args = json.loads(slot["args"] or "{}")
        except Exception:
            args = {}
        tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], arguments=args))
    return {
        "text": text,
        "tool_calls": tool_calls,
        "raw_assistant_msg": {"role": "assistant", "content": text,
                              "tool_calls": tool_calls},
        "provider": provider, "model": model, "error": None,
    }


# ---------------------------------------------------------------------------
# Anthropic adapter (tool_use / tool_result content blocks)
# ---------------------------------------------------------------------------

def _msgs_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Returns (system_prompt, anthropic_messages). System is a separate param."""
    system = ""
    out: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "system":
            system = m.get("content", "")
        elif role == "tool":
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            }]})
        elif role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                blocks.append({"type": "tool_use", "id": tc.id,
                               "name": tc.name, "input": tc.arguments})
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return system, out


def _complete_anthropic(model: str, messages: list[dict], tools: list[dict]) -> dict:
    from anthropic import Anthropic
    client = Anthropic(api_key=_env("ANTHROPIC_API_KEY"))
    system, amsgs = _msgs_to_anthropic(messages)
    kwargs: dict[str, Any] = {
        "model": model, "max_tokens": 2048, "messages": amsgs,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = _tools_anthropic_format(tools)
    resp = client.messages.create(**kwargs)
    text = ""
    tool_calls: list[ToolCall] = []
    for block in resp.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name,
                                       arguments=dict(block.input or {})))
    return {
        "text": text, "tool_calls": tool_calls,
        "raw_assistant_msg": {"role": "assistant", "content": text,
                              "tool_calls": tool_calls},
        "provider": "anthropic", "model": model, "error": None,
    }


# ---------------------------------------------------------------------------
# Gemini adapter (function_call / function_response Parts)
# ---------------------------------------------------------------------------

def _complete_gemini(model: str, messages: list[dict], tools: list[dict],
                     on_token=None) -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_env("GEMINI_API_KEY"))

    system = ""
    contents: list = []
    for m in messages:
        role = m["role"]
        if role == "system":
            system = m.get("content", "")
        elif role == "tool":
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(
                    name=m.get("name", "tool"),
                    response={"result": m.get("content", "")},
                )]))
        elif role == "assistant" and m.get("tool_calls"):
            parts = []
            if m.get("content"):
                parts.append(types.Part(text=m["content"]))
            for tc in m["tool_calls"]:
                parts.append(types.Part(function_call=types.FunctionCall(
                    name=tc.name, args=tc.arguments)))
            contents.append(types.Content(role="model", parts=parts))
        else:
            grole = "user" if role == "user" else "model"
            contents.append(types.Content(role=grole,
                                          parts=[types.Part(text=m.get("content", ""))]))

    cfg_kwargs: dict[str, Any] = {"temperature": 0.2}
    if system:
        cfg_kwargs["system_instruction"] = system
    if tools:
        cfg_kwargs["tools"] = _tools_gemini_format(tools)
    config = types.GenerateContentConfig(**cfg_kwargs)

    text = ""
    tool_calls: list[ToolCall] = []

    def _consume_parts(parts, stream: bool) -> None:
        nonlocal text
        for part in (parts or []):
            piece = getattr(part, "text", None)
            if piece:
                text += piece
                if stream and on_token:
                    try:
                        on_token(piece)
                    except Exception:
                        pass
            fc = getattr(part, "function_call", None)
            if fc:
                tool_calls.append(ToolCall(
                    id=f"gemini_{fc.name}_{len(tool_calls)}",
                    name=fc.name, arguments=dict(fc.args or {})))

    use_stream = on_token is not None and hasattr(client.models, "generate_content_stream")
    try:
        if use_stream:
            for chunk in client.models.generate_content_stream(
                    model=model, contents=contents, config=config):
                for cand in (chunk.candidates or []):
                    _consume_parts(getattr(getattr(cand, "content", None), "parts", None), True)
        else:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            for cand in (resp.candidates or []):
                _consume_parts(getattr(getattr(cand, "content", None), "parts", None), False)
            if not text:
                text = getattr(resp, "text", "") or ""
    except Exception as exc:                                          # noqa: BLE001
        if not text:
            return {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                    "provider": "gemini", "model": model,
                    "error": f"{type(exc).__name__}: {exc}"}

    return {
        "text": text, "tool_calls": tool_calls,
        "raw_assistant_msg": {"role": "assistant", "content": text,
                              "tool_calls": tool_calls},
        "provider": "gemini", "model": model, "error": None,
    }


# ---------------------------------------------------------------------------
# Unified entry point (with cross-provider failover)
# ---------------------------------------------------------------------------

# Error substrings that mean "this provider is unavailable right now — try the
# next one" (quota / rate / auth / transient / model-not-found). A genuinely
# malformed request won't match, so it returns immediately instead of retrying
# the same bad call against every provider.
_FAILOVER_MARKERS = (
    "429", "quota", "rate", "exhausted", "resource_exhausted",
    "unavailable", "503", "500", "overloaded", "temporarily",
    "timeout", "timed out", "connection", "connecterror",
    "auth", "api key", "api_key", "unauthorized", "permission",
    "not found", "deployment", "model_not_found", "no api key",
    "no adapter", "has no api key",
    # billing / out-of-credit (e.g. Together "402 credit_limit") — a dead paid
    # tier must fall over to a free provider (or local Ollama), not surface the
    # raw billing error to the user mid-chat.
    "402", "credit", "credit_limit", "billing", "insufficient", "payment",
)


def _is_failover_error(err: str) -> bool:
    e = (err or "").lower()
    return any(m in e for m in _FAILOVER_MARKERS)


# Paid APIs — used ONLY when explicitly chosen as the primary provider, never as
# an automatic failover target (so a free-tier rate-limit can't silently start
# spending money). Free/local providers — gemini (free tier), groq (free tier),
# ollama (local) — are always eligible for auto-failover.
_PAID_PROVIDERS = {"azure", "openai", "anthropic"}


def _plog(msg: str) -> None:
    """Append a line to logs/chat_timing.log (diagnostics; console is hidden)."""
    try:
        import time as _t
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        with open(root / "logs" / "chat_timing.log", "a", encoding="utf-8") as f:
            f.write(f"{_t.strftime('%H:%M:%S')}    [prov] {msg}\n")
    except Exception:
        pass


def _call_provider(prov: str, mdl: str, messages: list[dict],
                   tools: list[dict], on_token=None) -> dict:
    import time as _t
    _t0 = _t.perf_counter()
    try:
        if prov in ("openai", "azure", "groq", "ollama"):
            r = _complete_openai(prov, mdl, messages, tools, on_token=on_token)
        elif prov == "anthropic":
            r = _complete_anthropic(mdl, messages, tools)
        elif prov == "gemini":
            r = _complete_gemini(mdl, messages, tools, on_token=on_token)
        else:
            r = {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                 "provider": prov, "model": mdl, "error": "no adapter matched"}
    except Exception as exc:                                          # noqa: BLE001
        r = {"text": "", "tool_calls": [], "raw_assistant_msg": None,
             "provider": prov, "model": mdl,
             "error": f"{type(exc).__name__}: {exc}"}
    _plog(f"{prov}:{mdl} took {(_t.perf_counter()-_t0):.1f}s "
          f"err={(r.get('error') or 'none')[:50]} tools={len(tools)}")
    return r


def complete_with_tools(messages: list[dict], tools: list[dict] | None = None,
                        provider: str | None = None, model: str | None = None,
                        on_token=None) -> dict:
    """
    Send a conversation + tool catalog to the active provider and return the
    normalized result dict. Never raises — returns error=... on any failure.

    Auto-failover: tries the resolved provider first, then every other
    key-configured provider, ending at local Ollama. A provider-level failure
    (quota/429/rate/auth/transient/model-not-found) falls through to the next;
    other errors return immediately. Never fails over once tokens have already
    streamed (that would double-render the answer).

    provider : override active provider (else resolve_provider())
    model    : override model (only applied to the resolved provider)
    on_token : optional callable(str) — fired per text delta for live streaming.
               OpenAI-format providers + gemini stream; anthropic returns whole.
    """
    primary = resolve_provider(provider)
    tools = tools or []

    # Build ordered candidate list: the chosen primary first (even if it's a
    # paid provider — that's an explicit choice), then FREE providers only as
    # auto-failover (paid APIs are never auto-tried), Ollama last (local).
    candidates: list[str] = []
    if primary in PROVIDERS and (_provider_has_key(primary) or primary == "ollama"):
        candidates.append(primary)
    for p in PROVIDERS:
        if p in candidates or p in _PAID_PROVIDERS:
            continue
        if _provider_has_key(p):
            candidates.append(p)
    if "ollama" not in candidates:
        candidates.append("ollama")

    # Guard on_token so we can detect (and stop) mid-stream failover.
    streamed = {"any": False}
    cb = None
    if on_token is not None:
        def cb(tok):                                                  # noqa: E306
            streamed["any"] = True
            on_token(tok)

    last: dict | None = None
    for prov in candidates:
        mdl = resolve_model(prov, model if prov == primary else None)
        res = _call_provider(prov, mdl, messages, tools, on_token=cb)
        if not res.get("error"):
            if prov != primary:
                print(f"[providers] failed over -> {prov}:{mdl}")
            return res
        last = res
        # Already streamed partial text → don't restart on another provider.
        if streamed["any"]:
            return res
        if not _is_failover_error(res["error"]):
            return res
        print(f"[providers] {prov} unavailable ({res['error'][:70]}) - failing over")

    return last or {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                    "provider": primary, "model": model or "",
                    "error": "all providers failed"}


if __name__ == "__main__":
    print("Available providers (key present?):")
    for p, ok in available_providers().items():
        print(f"  {p:10} {'READY' if ok else '-- no key'}")
    print(f"\nresolve_provider() -> {resolve_provider()}")
    print(f"resolve_model()    -> {resolve_model(resolve_provider())}")
