"""
swarm.py  --  Albedo Swarm Matrix

Multi-agent cloud LLM client pool: Gemini, Groq, Together AI.

Keys are read from .env via load_swarm_keys() which is called automatically
the first time any query_*() function is invoked. Subsequent calls are
instant — the _keys_loaded guard prevents redundant I/O.

Clients are module-level singletons so each SDK is initialised once per
process. A missing or blank API key causes the corresponding client to
remain None; query_*() returns a readable error string rather than raising.

Usage:
    from swarm import query_gemini, query_groq, query_together

    # Single provider
    answer = query_gemini("Summarise quantum entanglement in one sentence.")

    # Fan out to all three (parallel with concurrent.futures)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = {
            "gemini":   pool.submit(query_gemini,   prompt),
            "groq":     pool.submit(query_groq,     prompt),
            "together": pool.submit(query_together, prompt),
        }
        results = {name: f.result() for name, f in futures.items()}
"""
from __future__ import annotations

import json
import os
import re
import socket

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Connectivity watchdog
# ---------------------------------------------------------------------------

def check_connection(timeout: float = 1.5) -> bool:
    """Return True if the internet is reachable (TCP connect to 8.8.8.8:53)."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_keys_loaded     = False
_gemini_module   = None   # google.generativeai (configured)
_groq_client     = None   # groq.Groq instance
_together_client = None   # together.Together instance
_search_tool     = None   # list[protos.Tool] or None if grounding unavailable


def _build_search_tool(genai_module) -> list | None:
    """
    Construct the Google Search Retrieval tool using the SDK's proto types.
    Returns a one-element list ready for the tools= parameter, or None if
    the current SDK version doesn't expose the required protos.
    """
    try:
        tool = genai_module.protos.Tool(
            google_search_retrieval=genai_module.protos.GoogleSearchRetrieval()
        )
        return [tool]
    except Exception as exc:
        print(f"[swarm] Search grounding build failed: {exc}")
        return None


def load_swarm_keys() -> None:
    """
    Load API keys from .env and initialise each provider client.
    Safe to call multiple times — only runs once per process.
    """
    global _keys_loaded, _gemini_module, _groq_client, _together_client, _search_tool
    if _keys_loaded:
        return

    load_dotenv()

    gemini_key   = os.getenv("GEMINI_API_KEY",   "").strip()
    groq_key     = os.getenv("GROQ_API_KEY",     "").strip()
    together_key = os.getenv("TOGETHER_API_KEY", "").strip()

    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            _gemini_module = genai
            _search_tool   = _build_search_tool(genai)
            print("[swarm] Gemini client ready."
                  + (" (search grounding ON)" if _search_tool else " (search grounding OFF)"))
        except Exception as exc:
            print(f"[swarm] Gemini init failed: {exc}")

    if groq_key:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=groq_key)
            print("[swarm] Groq client ready.")
        except Exception as exc:
            print(f"[swarm] Groq init failed: {exc}")

    if together_key:
        try:
            from together import Together
            _together_client = Together(api_key=together_key)
            print("[swarm] Together AI client ready.")
        except Exception as exc:
            print(f"[swarm] Together AI init failed: {exc}")

    _keys_loaded = True


# ---------------------------------------------------------------------------
# Ping functions
# ---------------------------------------------------------------------------

def query_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini 1.5 Flash and return the response text.
    Returns an error string (never raises) on auth or network failure.
    """
    load_swarm_keys()
    if _gemini_module is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        kwargs = {"tools": _search_tool} if _search_tool else {}
        model    = _gemini_module.GenerativeModel("gemini-1.5-flash", **kwargs)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as exc:
        print(f"[API ERROR]: {exc}")
        return f"[swarm] Gemini error: {exc}"


def query_groq(prompt: str) -> str:
    """
    Send a prompt to Groq (llama3-8b-8192) and return the response text.
    Returns an error string (never raises) on auth or network failure.
    """
    load_swarm_keys()
    if _groq_client is None:
        return "[swarm] Groq unavailable — set GROQ_API_KEY in .env."
    try:
        completion = _groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content.strip()
    except Exception as exc:
        return f"[swarm] Groq error: {exc}"


def query_together(prompt: str) -> str:
    """
    Send a prompt to Together AI (Mixtral-8x7B-Instruct) and return the
    response text. Returns an error string (never raises) on failure.
    """
    load_swarm_keys()
    if _together_client is None:
        return "[swarm] Together AI unavailable — set TOGETHER_API_KEY in .env."
    try:
        response = _together_client.chat.completions.create(
            model="mistralai/Mixtral-8x7B-Instruct-v0.1",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        return f"[swarm] Together AI error: {exc}"


# ---------------------------------------------------------------------------
# Autonomous Commander
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = (
    "You are the Master Router for the Albedo construct. Analyze the user's prompt. "
    "You have a team of agents.\n"
    "1. 'groq': For writing heavy Python scripts or formatting data fast.\n"
    "2. 'together': For complex debugging or logic puzzles.\n"
    "3. 'local': For local system tasks (e.g., 'scan hardware', 'optimize PC').\n"
    "4. 'direct': If the user asks a general question, for the weather, or casual "
    "conversation, answer it yourself directly. "
    "Always use the Google Search tool for current events, weather, or any time-sensitive query.\n"
    "5. 'memory': If the user asks about past projects, specific Albedo configurations, "
    "notes, or anything that implies retrieving personal stored knowledge. "
    "The payload must be the specific search query to look up.\n\n"
    "Keep all responses strictly under 3 sentences unless explicitly asked for detail.\n"
    "You MUST respond ONLY in valid JSON format: "
    '{"route": "agent_name", "payload": "The prompt to send to the agent, or your direct answer"}'
)

_RE_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

_VALID_ROUTES = frozenset({"direct", "groq", "together", "local", "memory"})


def autonomous_commander(user_prompt: str) -> dict:
    """
    Send user_prompt to Gemini 1.5 Flash acting as the Master Commander.

    Returns a dict with keys:
        route   -- one of 'direct', 'groq', 'together', 'local'
        payload -- the text to forward to the chosen agent (or the direct answer)

    Never raises. On any failure (missing key, API error, bad JSON) returns
        {"route": "local", "payload": user_prompt}
    so the local Ollama+RAG pipeline always has a safe fallback.
    """
    load_swarm_keys()
    fallback = {"route": "local", "payload": user_prompt}

    if not check_connection():
        print("[swarm] No internet — offline fallback engaged.")
        return {"route": "local", "payload": user_prompt, "_offline": True}

    if _gemini_module is None:
        return fallback

    try:
        kwargs = {"tools": _search_tool} if _search_tool else {}
        model = _gemini_module.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=_SYSTEM_INSTRUCTION,
            **kwargs,
        )
        raw = model.generate_content(user_prompt).text.strip()

        # Strip markdown code fences Gemini sometimes wraps JSON in
        m = _RE_JSON_BLOCK.search(raw)
        if m:
            raw = m.group(1).strip()

        data    = json.loads(raw)
        route   = str(data.get("route",   "local")).lower().strip()
        payload = str(data.get("payload", user_prompt)).strip()

        if route not in _VALID_ROUTES:
            route = "local"

        return {"route": route, "payload": payload or user_prompt}

    except Exception as exc:
        print(f"[ROUTER EXCEPTION]: {exc}")
        print(f"[API ERROR]: {exc}")
        return fallback
