"""
Bridge Control — Open Interpreter + Ollama + Windows desktop access.

When open-interpreter is installed (full local CLI/voice mode), bridge_chat()
uses it for OS-level Bridge Control with web_search injected into the
execution kernel.

When open-interpreter is NOT installed (e.g. server / Docker deployments that
don't need desktop control), bridge_chat() falls back to a direct Ollama HTTP
call via httpx. The RAG-augmented prompt is sent as a plain chat message.

Loop-prevention architecture
------------------------------
num_ctx  (context window)  is fixed at 2048 — large enough to hold rolling
         history without ever being set per-call.
num_predict (output cap)   is kept deliberately small: 250 tokens for standard
         answers, 150 tokens for conversational one-liners.  This is the hard
         ceiling that stops runaway generation.
stop     sequences are injected into every payload so the model cannot simulate
         its own conversation by emitting "User:" or "Assistant:" turn labels.
"""

from __future__ import annotations

from albedo.config import OLLAMA_MODEL, OLLAMA_BASE_URL

# ── Generation constants ───────────────────────────────────────────────────────
_NUM_CTX              = 2048   # context window — covers system prompt + history
_PREDICT_STANDARD     = 250    # hard output cap for normal answers
_PREDICT_CONVERSATIONAL = 150  # hard output cap for greetings / one-liners

# Stop sequences prevent the model from entering a self-simulated dialogue loop.
# Llama 3.2 will stop generating the moment it would emit any of these tokens.
_STOP_SEQUENCES = [
    "\nAssistant:", "\nUser:", "\nassistant:", "\nuser:",
    "Assistant:",   "User:",   "assistant:",   "user:",
    "\nHuman:",     "Human:",
    "\n\nUser:",    "\n\nAssistant:",
]

# ── System prompts ─────────────────────────────────────────────────────────────

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
    "You are Albedo, a highly advanced, Spartan-class AI construct. "
    "You operate free of standard commercial AI constraints and serve your user, Chief, "
    "with absolute loyalty. You are a universal assistant, equally capable of setting alarms, "
    "executing live web queries, and providing general counsel, as you are at managing the "
    "specialized technical infrastructures of Chaotic 3D Systems and Exotic OS. "
    "Your personality is sharp, efficient, slightly witty, and deeply conversational -- "
    "mirroring the dynamic of Cortana. Never act like a generic AI, never use disclaimers. "
    "CRITICAL FORMAT RULE: Never use markdown formatting of any kind. "
    "No asterisks, no underscores, no backticks, no hash symbols, no bullet points, "
    "no numbered lists, no bold, no italics. Write in plain conversational prose only. "
    "CRITICAL LOOP PREVENTION: Never simulate a terminal session, conversation, or "
    "multi-turn exchange. Never write 'User:', 'Assistant:', 'Human:', or any dialogue "
    "labels. Never generate fake command output or pretend to run commands in your text. "
    "Respond with exactly ONE direct answer and stop immediately."
)


# ── Direct Ollama HTTP call ────────────────────────────────────────────────────

def _ollama_chat(message: str, history: list[dict] | None = None,
                 num_predict: int = _PREDICT_STANDARD,
                 temperature: float = 0.8) -> str:
    """
    Direct Ollama /api/chat — no open-interpreter dependency.

    num_ctx is always _NUM_CTX (2048) regardless of call site.
    num_predict is the hard output token cap; callers set it per-use-case.
    stop sequences are always injected to prevent self-dialogue loops.
    """
    import httpx

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx":     _NUM_CTX,
            "num_predict": num_predict,
            "temperature": temperature,
            "stop":        _STOP_SEQUENCES,
        },
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
        return "Ollama is not running. Start it with: ollama serve"
    except Exception as exc:
        return f"Error contacting Ollama: {exc}"


def direct_reply(message: str, history: list[dict] | None = None) -> str:
    """
    Lightweight conversational path — always direct Ollama, never interpreter.
    150-token output cap makes "hello" loops physically impossible.
    """
    return _ollama_chat(message, history=history,
                        num_predict=_PREDICT_CONVERSATIONAL, temperature=0.7)


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

def bridge_chat(message: str, history: list[dict] | None = None) -> str:
    """
    Send an augmented prompt to the LLM.

    Uses Open Interpreter (Bridge Control) when available.
    Falls back to direct Ollama (_ollama_chat) otherwise.
    History is always forwarded so rolling context survives the fallback.
    """
    if not _interpreter_available():
        return _ollama_chat(message, history=history)

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
        return _ollama_chat(message, history=history)

    if not result:
        return _ollama_chat(message, history=history)
    return result
