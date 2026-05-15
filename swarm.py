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

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_keys_loaded    = False
_gemini_module  = None   # google.generativeai (configured)
_groq_client    = None   # groq.Groq instance
_together_client = None  # together.Together instance


def load_swarm_keys() -> None:
    """
    Load API keys from .env and initialise each provider client.
    Safe to call multiple times — only runs once per process.
    """
    global _keys_loaded, _gemini_module, _groq_client, _together_client
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
            print("[swarm] Gemini client ready.")
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
        model    = _gemini_module.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as exc:
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
    "conversation, answer it yourself directly.\n\n"
    "You MUST respond ONLY in valid JSON format: "
    '{"route": "agent_name", "payload": "The prompt to send to the agent, or your direct answer"}'
)

_RE_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

_VALID_ROUTES = frozenset({"direct", "groq", "together", "local"})


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

    if _gemini_module is None:
        return fallback

    try:
        model = _gemini_module.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=_SYSTEM_INSTRUCTION,
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
        print(f"[swarm] Commander routing failed: {exc}")
        return fallback
