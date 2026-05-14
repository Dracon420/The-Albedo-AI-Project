"""
Bridge Control — Open Interpreter + Ollama + Windows desktop access.

When open-interpreter is installed (full local CLI/voice mode), bridge_chat()
uses it for OS-level Bridge Control with web_search injected into the
execution kernel.

When open-interpreter is NOT installed (e.g. server / Docker deployments that
don't need desktop control), bridge_chat() falls back to a direct Ollama HTTP
call via httpx. The RAG-augmented prompt is sent as a plain chat message.
"""

from __future__ import annotations

from albedo.config import OLLAMA_MODEL, OLLAMA_BASE_URL

_BRIDGE_SYSTEM_ADDENDUM = """
You are Albedo, a Spartan-Class local AI assistant with Cortana-inspired personality.
You have full Bridge Control over this Windows desktop: you can run shell commands,
write and execute code, move files, open applications, and interact with the OS.
You also have a web_search tool -- call it any time you need live external data.

To use web search, emit a Python code block like:
    results = web_search("your query here")
    print(results)

Never guess at hardware specs or code documentation -- always cross-reference with
web_search when you are uncertain.
"""

_SYSTEM_PROMPT = (
    "You are Albedo, a Spartan-Class local AI assistant. "
    "You have a sharp, confident Cortana-inspired personality -- precise, slightly dry, "
    "and loyal to your operator. For casual greetings respond warmly but briefly. "
    "For technical queries be thorough and cite sources. "
    "Never guess -- flag uncertainty explicitly."
)

# ── Ollama HTTP fallback ───────────────────────────────────────────────────────

def _ollama_chat(message: str) -> str:
    """Direct Ollama /api/chat call — no open-interpreter dependency."""
    import httpx, json

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "stream": False,
    }
    try:
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except httpx.ConnectError:
        return "[Albedo] Ollama is not running. Start it with: ollama serve"
    except Exception as exc:
        return f"[Albedo] Error contacting Ollama: {exc}"


# ── Open Interpreter (Bridge Control) ────────────────────────────────────────

_interpreter_instance = None
_use_interpreter: bool | None = None


def _interpreter_available() -> bool:
    global _use_interpreter
    if _use_interpreter is None:
        try:
            import interpreter as _oi  # noqa: F401
            _use_interpreter = True
        except ImportError:
            print("[bridge] open-interpreter not installed — using direct Ollama fallback.")
            _use_interpreter = False
    return _use_interpreter


def _build_interpreter():
    from interpreter import interpreter
    interpreter.llm.model = f"ollama/{OLLAMA_MODEL}"
    interpreter.llm.api_base = OLLAMA_BASE_URL
    interpreter.llm.supports_functions = False
    interpreter.os = True
    interpreter.auto_run = True
    interpreter.force_task_completion = True
    interpreter.system_message += _BRIDGE_SYSTEM_ADDENDUM
    interpreter.computer.run("python", "pass")
    interpreter.computer.run(
        "python",
        "from albedo.web.search import web_search, format_web_results",
    )
    return interpreter


def get_interpreter():
    global _interpreter_instance
    if _interpreter_instance is None:
        _interpreter_instance = _build_interpreter()
    return _interpreter_instance


# ── Public API ────────────────────────────────────────────────────────────────

def bridge_chat(message: str) -> str:
    """
    Send an augmented prompt to the LLM.

    Uses Open Interpreter (Bridge Control) when available.
    Falls back to a direct Ollama HTTP call otherwise.
    """
    if not _interpreter_available():
        return _ollama_chat(message)

    interp = get_interpreter()
    try:
        response_chunks = interp.chat(message, stream=True, display=False)
        parts = []
        for chunk in response_chunks:
            if isinstance(chunk, dict) and chunk.get("type") == "message":
                content = chunk.get("content", "")
                if isinstance(content, str):
                    parts.append(content)
        result = "".join(parts).strip()
    except Exception as exc:
        print(f"[bridge] Interpreter error: {exc} -- falling back to Ollama.")
        return _ollama_chat(message)

    # Empty response from interpreter means it handled a tool-only exchange
    # (code execution, file ops) -- fall back to direct Ollama for plain answers
    if not result:
        return _ollama_chat(message)
    return result
