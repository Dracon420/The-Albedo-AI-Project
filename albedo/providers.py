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
    # settings.json brain_model
    try:
        from pathlib import Path
        sp = Path(__file__).resolve().parent.parent / "settings.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            if s.get("brain_model"):
                return str(s["brain_model"])
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
    """Construct the right client for an OpenAI-format provider."""
    if provider == "openai":
        from openai import OpenAI
        return OpenAI(api_key=_env("OPENAI_API_KEY"))
    if provider == "azure":
        from openai import AzureOpenAI
        ver = _env("AZURE_OPENAI_API_VERSION") or _AZURE_TOOLS_API_VERSION
        return AzureOpenAI(
            api_key=_env("AZURE_OPENAI_KEY"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            api_version=ver,
        )
    if provider == "groq":
        from openai import OpenAI
        return OpenAI(api_key=_env("GROQ_API_KEY"),
                      base_url="https://api.groq.com/openai/v1")
    if provider == "ollama":
        from openai import OpenAI
        base = (_env("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        return OpenAI(api_key="ollama", base_url=f"{base}/v1")
    raise ValueError(f"not an OpenAI-format provider: {provider}")


def _complete_openai(provider: str, model: str, messages: list[dict],
                     tools: list[dict]) -> dict:
    client = _openai_client(provider)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": _msgs_to_openai(messages),
    }
    if tools:
        kwargs["tools"] = _tools_openai_format(tools)
        kwargs["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0].message
    tool_calls: list[ToolCall] = []
    for tc in (choice.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return {
        "text": choice.content or "",
        "tool_calls": tool_calls,
        "raw_assistant_msg": {"role": "assistant", "content": choice.content,
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

def _complete_gemini(model: str, messages: list[dict], tools: list[dict]) -> dict:
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

    resp = client.models.generate_content(model=model, contents=contents, config=config)

    text = ""
    tool_calls: list[ToolCall] = []
    try:
        for cand in (resp.candidates or []):
            for part in (cand.content.parts or []):
                if getattr(part, "text", None):
                    text += part.text
                fc = getattr(part, "function_call", None)
                if fc:
                    tool_calls.append(ToolCall(
                        id=f"gemini_{fc.name}_{len(tool_calls)}",
                        name=fc.name, arguments=dict(fc.args or {})))
    except Exception:
        text = getattr(resp, "text", "") or text

    return {
        "text": text, "tool_calls": tool_calls,
        "raw_assistant_msg": {"role": "assistant", "content": text,
                              "tool_calls": tool_calls},
        "provider": "gemini", "model": model, "error": None,
    }


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def complete_with_tools(messages: list[dict], tools: list[dict] | None = None,
                        provider: str | None = None, model: str | None = None) -> dict:
    """
    Send a conversation + tool catalog to the active provider and return the
    normalized result dict. Never raises — returns error=... on any failure.

    messages : neutral message list (see module docstring)
    tools    : neutral tool schemas from agent_tools.get_tool_schemas() (or None)
    provider : override active provider (else resolve_provider())
    model    : override model (else resolve_model())
    """
    prov = resolve_provider(provider)
    if prov not in PROVIDERS:
        return {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                "provider": prov, "model": model or "",
                "error": f"Unknown provider: {prov!r}. Choose from {PROVIDERS}."}
    if not _provider_has_key(prov):
        return {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                "provider": prov, "model": model or "",
                "error": f"Provider {prov!r} has no API key configured."}

    mdl = resolve_model(prov, model)
    tools = tools or []
    try:
        if prov in ("openai", "azure", "groq", "ollama"):
            return _complete_openai(prov, mdl, messages, tools)
        if prov == "anthropic":
            return _complete_anthropic(mdl, messages, tools)
        if prov == "gemini":
            return _complete_gemini(mdl, messages, tools)
    except Exception as exc:
        return {"text": "", "tool_calls": [], "raw_assistant_msg": None,
                "provider": prov, "model": mdl,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"text": "", "tool_calls": [], "raw_assistant_msg": None,
            "provider": prov, "model": mdl, "error": "no adapter matched"}


if __name__ == "__main__":
    print("Available providers (key present?):")
    for p, ok in available_providers().items():
        print(f"  {p:10} {'READY' if ok else '-- no key'}")
    print(f"\nresolve_provider() -> {resolve_provider()}")
    print(f"resolve_model()    -> {resolve_model(resolve_provider())}")
