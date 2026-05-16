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

import warnings

from dotenv import load_dotenv

# Suppress the google-generativeai deprecation FutureWarning at import time.
warnings.filterwarnings("ignore", category=FutureWarning,
                        module="google.generativeai")

# Load .env now so all env vars are available before any function is called.
load_dotenv()

_location     = os.getenv("NODE_LOCATION", "").strip() or "Raymond, Washington"
_gemini_model = os.getenv("GEMINI_MODEL",  "gemini-2.0-flash").strip()

# ---------------------------------------------------------------------------
# Semantic location interceptor
# Physically rewrites location-relative trigger phrases in the user string
# before API transmission so Gemini never sees "near me" or "my location".
# ---------------------------------------------------------------------------

# Single combined pattern for the three primary trigger phrases (directive spec)
_RE_LOCATION_PRIMARY = re.compile(
    r'\b(near me|my location|where I am)\b', re.IGNORECASE
)
# Secondary triggers mapped to tailored replacements
_LOCATION_SECONDARY: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bmy area\b',  re.IGNORECASE), f'the {_location} area'),
    (re.compile(r'\bmy city\b',  re.IGNORECASE), _location),
    (re.compile(r'\bmy town\b',  re.IGNORECASE), _location),
    (re.compile(r'\bnearby\b',   re.IGNORECASE), f'near {_location}'),
    (re.compile(r'\blocally\b',  re.IGNORECASE), f'in {_location}'),
]


def _mutate_location(prompt: str) -> str:
    """Replace location-relative phrases with the actual node location."""
    prompt = _RE_LOCATION_PRIMARY.sub(f'in {_location}', prompt)
    for pattern, replacement in _LOCATION_SECONDARY:
        prompt = pattern.sub(replacement, prompt)
    return prompt

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
            print(f"[swarm] Gemini client ready (model: {_gemini_model}).")
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
    Send a prompt to Gemini and return the response text.
    Returns an error string (never raises) on auth or network failure.
    """
    load_swarm_keys()
    if _gemini_module is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        gen_cfg = _gemini_module.GenerationConfig(temperature=0.1)
        model   = _gemini_module.GenerativeModel(
            model_name=_gemini_model, generation_config=gen_cfg)
        return model.generate_content(prompt).text.strip()
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


def direct_gemini_search(prompt: str) -> str:
    """
    Send a prompt directly to Gemini with Google Search grounding and return
    the plain-text answer.  Non-streaming — avoids the ReAct agent loop that
    stream=True triggers when grounding tools are active.

    Use this for weather queries and any intercepted 'direct answer' path
    that must bypass autonomous_commander() entirely.

    Never raises — returns an error string on failure.
    """
    load_swarm_keys()
    prompt = _mutate_location(prompt)
    if _gemini_module is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        gen_cfg = _gemini_module.GenerationConfig(temperature=0.1)
        instruction = (
            "You are Albedo, a Spartan-Class AI. "
            "NEVER introduce yourself. NEVER explain your search process. "
            "NEVER write code, plans, or multi-step reasoning. "
            "Provide ONLY the direct answer in one short sentence. "
            "Format weather as: 'The weather in [Location] is [Temp] with [Conditions].' "
            "Never use markdown."
        )
        try:
            model = _gemini_module.GenerativeModel(
                model_name=_gemini_model,
                tools='google_search_retrieval',
                system_instruction=instruction,
                generation_config=gen_cfg,
            )
        except Exception:
            model = _gemini_module.GenerativeModel(
                model_name=_gemini_model,
                system_instruction=instruction,
                generation_config=gen_cfg,
            )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as exc:
        print(f"[swarm] direct_gemini_search error: {exc}")
        return f"[swarm] Search error: {exc}"


def query_gemini_stream(prompt: str, on_sentence=None) -> str:
    """
    Stream a response from Gemini 1.5 Flash using _DIRECT_ANSWER_INSTRUCTION.

    on_sentence(sentence: str) is called for each complete sentence as it
    arrives from the stream, enabling zero-latency TTS queuing.  If
    on_sentence is None, the full text is collected and returned without
    any mid-stream callbacks.

    Returns the full concatenated response text.
    Never raises — returns an error string on failure.
    """
    load_swarm_keys()
    prompt = _mutate_location(prompt)
    if _gemini_module is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        gen_cfg = _gemini_module.GenerationConfig(temperature=0.1)
        # Directive Phase 3: explicit native tool payload — string shorthand
        # 'google_search_retrieval' is the only syntax confirmed working on
        # SDK 0.8.x.  Do NOT use response_mime_type here — JSON mode silently
        # drops grounding.
        try:
            model = _gemini_module.GenerativeModel(
                model_name=_gemini_model,
                tools='google_search_retrieval',
                system_instruction=_DIRECT_ANSWER_INSTRUCTION,
                generation_config=gen_cfg,
            )
        except Exception:
            # Older SDK: fall back to no tools (hallucination risk lower than crash)
            model = _gemini_module.GenerativeModel(
                model_name=_gemini_model,
                system_instruction=_DIRECT_ANSWER_INSTRUCTION,
                generation_config=gen_cfg,
            )
        full_text = ""
        buffer    = ""
        for chunk in model.generate_content(prompt, stream=True):
            try:
                chunk_text = chunk.text
            except Exception:
                continue
            buffer    += chunk_text
            full_text += chunk_text
            if on_sentence is None:
                continue
            while True:
                end_idx = -1
                for punct in ('.', '!', '?', '\n'):
                    idx = buffer.find(punct)
                    if idx >= 0 and (end_idx < 0 or idx < end_idx):
                        end_idx = idx
                if end_idx < 0:
                    break
                sentence = buffer[:end_idx + 1].strip()
                if sentence:
                    on_sentence(sentence)
                buffer = buffer[end_idx + 1:]
        if on_sentence and buffer.strip():
            on_sentence(buffer.strip())
        return full_text.strip()
    except Exception as exc:
        print(f"[API ERROR]: {exc}")
        return f"[swarm] Gemini error: {exc}"


# ---------------------------------------------------------------------------
# Autonomous Commander
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = (
    "You are Albedo, a Spartan-Class AI master router. "
    "NEVER introduce yourself. NEVER explain your reasoning or search process. "
    "Analyze the user prompt and respond ONLY with valid JSON.\n\n"
    "Route to one of:\n"
    "  'groq'    — Python scripts or fast data formatting\n"
    "  'together' — complex debugging or logic puzzles\n"
    "  'local'   — local system tasks (scan hardware, optimize PC)\n"
    "  'direct'  — general questions, weather, casual conversation — answer directly\n"
    "  'memory'  — past projects, Albedo configs, personal notes\n\n"
    "Rules:\n"
    "  - Keep all answers under 2 sentences.\n"
    "  - Format weather as: 'The weather in [Location] is [Temp] with [Conditions].'\n"
    "  - ONLY output JSON. No prose, no preamble.\n"
    'Respond ONLY: {"route": "agent_name", "payload": "direct answer or forwarded prompt"}'
)

_RE_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

_VALID_ROUTES = frozenset({"direct", "groq", "together", "local", "memory"})

_DIRECT_ANSWER_INSTRUCTION = (
    "You are Albedo, a Spartan-Class AI. "
    "NEVER introduce yourself. NEVER explain your search process or thought process. "
    "Provide ONLY the direct answer. Keep all responses under 2 sentences. "
    "Format weather as: 'The weather in [Location] is [Temp] with [Conditions].' "
    "Never use markdown formatting. Write in plain conversational prose only."
)


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
    user_prompt = _mutate_location(user_prompt)
    fallback = {"route": "local", "payload": user_prompt}

    if not check_connection():
        print("[swarm] No internet — offline fallback engaged.")
        return {"route": "local", "payload": user_prompt, "_offline": True}

    if _gemini_module is None:
        return fallback

    try:
        try:
            cmd_cfg = _gemini_module.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json",
            )
        except Exception:
            cmd_cfg = _gemini_module.GenerationConfig(temperature=0.1)

        # No search tools — JSON mode (response_mime_type) and grounding are
        # mutually exclusive; grounding is silently dropped when both present.
        # The commander only routes — it does not need live web data.
        model = _gemini_module.GenerativeModel(
            model_name=_gemini_model,
            system_instruction=_SYSTEM_INSTRUCTION,
            generation_config=cmd_cfg,
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
