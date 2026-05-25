"""
swarm.py  --  Albedo Swarm Matrix

Multi-agent cloud LLM client pool: Gemini (google-genai SDK), Groq, Together AI.

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

# Suppress deprecation noise from SDK internals.
warnings.filterwarnings("ignore", category=FutureWarning,      module="google")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="google")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="GPUtil")
# duckduckgo_search uses stacklevel=2 in its rename warning, so Python attributes
# it to the *caller* (swarm.py), not to duckduckgo_search. Module filter never
# fires; filter by message text instead.
warnings.filterwarnings("ignore", message=".*duckduckgo.search.*renamed.*ddgs.*",
                        category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*renamed.*`ddgs`.*",
                        category=RuntimeWarning)

# Load .env now so all env vars are available before any function is called.
load_dotenv()

_location     = os.getenv("NODE_LOCATION", "").strip() or "Raymond, Washington"
# The google-genai SDK targets the v1beta endpoint. Gemini 1.5 models only exist
# on v1 — they 404 on v1beta. gemini-2.0-flash-lite is the correct free-tier
# model for v1beta: 1500 req/day, no grounding quota, resolves correctly.
_gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"

# ---------------------------------------------------------------------------
# Semantic location interceptor
# Physically rewrites location-relative trigger phrases in the user string
# before API transmission so Gemini never sees "near me" or "my location".
# ---------------------------------------------------------------------------

_RE_LOCATION_PRIMARY = re.compile(
    r'\b(near me|my location|where I am)\b', re.IGNORECASE
)
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
# Native DDG web scraper — decoupled from LLM provider quotas
# ---------------------------------------------------------------------------

def native_web_search(query: str, max_results: int = 3) -> str:
    """
    Scrape the top `max_results` DuckDuckGo text snippets for `query` and
    return them as a single formatted context string.

    Never raises — returns 'Local search node offline.' on any failure so
    callers always have a meaningful signal to inject into the prompt.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # silence all DDGS rename warnings
            from duckduckgo_search import DDGS
            results = DDGS().text(query, max_results=max_results)
        if not results:
            return "Local search node offline."
        parts = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "").strip()
            body  = r.get("body",  "").strip()
            if body:
                parts.append(f"[{i}] {title}: {body}" if title else f"[{i}] {body}")
        return "\n".join(parts) if parts else "Local search node offline."
    except Exception as exc:
        print(f"[swarm] DDG search error: {exc}")
        return "Local search node offline."


# ---------------------------------------------------------------------------
# Immersive error string — shown in UI chat feed on any Gemini API failure.
# Raw exception JSON must never reach the user.
# ---------------------------------------------------------------------------

_UPLINK_ERROR = (
    "[SYSTEM ERROR] Uplink to Gemini Swarm failed. "
    "API Node rejected the connection. Check API key quotas."
)

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_keys_loaded     = False
_gemini_client   = None   # google.genai.Client instance
_groq_client     = None   # groq.Groq instance
_together_client = None   # together.Together instance


def load_swarm_keys() -> None:
    """
    Load API keys from .env and initialise each provider client.
    Safe to call multiple times — only runs once per process.
    """
    global _keys_loaded, _gemini_client, _groq_client, _together_client
    if _keys_loaded:
        return

    load_dotenv()

    gemini_key   = os.getenv("GEMINI_API_KEY",   "").strip()
    groq_key     = os.getenv("GROQ_API_KEY",     "").strip()
    together_key = os.getenv("TOGETHER_API_KEY", "").strip()

    if gemini_key:
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=gemini_key)
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


def reinit_swarm_clients() -> None:
    """Force a full re-initialisation of all provider clients from the current .env.
    Call this after API keys are changed at runtime."""
    global _keys_loaded, _gemini_client, _groq_client, _together_client
    _keys_loaded     = False
    _gemini_client   = None
    _groq_client     = None
    _together_client = None
    load_swarm_keys()


# ---------------------------------------------------------------------------
# Ping functions
# ---------------------------------------------------------------------------

def query_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini and return the response text.
    Returns an error string (never raises) on auth or network failure.
    """
    load_swarm_keys()
    if _gemini_client is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        from google.genai import types
        response = _gemini_client.models.generate_content(
            model=_gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return response.text.strip()
    except Exception as exc:
        print(f"\n[CRITICAL DEBUG] Raw Swarm Exception: {exc}\n")
        return _UPLINK_ERROR


def query_groq(prompt: str) -> str:
    """
    Send a prompt to Groq (llama-3.1-8b-instant) and return the response text.
    Returns an error string (never raises) on auth or network failure.
    """
    load_swarm_keys()
    if _groq_client is None:
        return "[swarm] Groq unavailable — set GROQ_API_KEY in .env."
    try:
        completion = _groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
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


_SEARCH_INSTRUCTION = (
    "You are Albedo, a Spartan-Class AI. "
    "NEVER introduce yourself. NEVER explain your reasoning or search process. "
    "NEVER write code, plans, or step-by-step breakdowns. "
    "Synthesise the provided background data into a direct, complete answer. "
    "Be concise but thorough — a sentence for simple facts, a short paragraph for complex ones. "
    "Format weather as: 'The weather in [Location] is [Temp] with [Conditions].' "
    "ALWAYS use Fahrenheit. NEVER substitute a nearby city — if the location has no data, say so. "
    "Never use markdown."
)

_RE_WEATHER    = re.compile(r'\bweather\b', re.IGNORECASE)
_RE_FILLER     = re.compile(
    r'\b(what|whats|is|the|weather|tell|me|give|current|forecast|'
    r'today|please|check|answer|reply|sentence|fahrenheit)\b',
    re.IGNORECASE,
)
# Extracts the location from the canonicalized weather prompt produced by gui.py
_RE_WEATHER_LOC = re.compile(
    r'current weather in (.+?)[\?.]', re.IGNORECASE
)


def _get_wttr_weather(location: str) -> str:
    """
    Fetch current conditions from wttr.in — free, no API key, no quota.
    Returns a plain-prose sentence on success, empty string on any failure.
    """
    import urllib.request
    import urllib.parse
    import json as _json
    try:
        encoded = urllib.parse.quote(location.strip())
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read())
        c        = data["current_condition"][0]
        desc     = c["weatherDesc"][0]["value"]
        temp_f   = c["temp_F"]
        feels_f  = c["FeelsLikeF"]
        humidity = c["humidity"]
        wind_mph = c["windspeedMiles"]
        print(f"[swarm] wttr.in: {location} → {desc} {temp_f}°F")
        return (
            f"Currently {desc} in {location}: {temp_f}°F "
            f"(feels like {feels_f}°F), humidity {humidity}%, "
            f"winds at {wind_mph} mph."
        )
    except Exception as exc:
        print(f"[swarm] wttr.in failed ({exc}), falling back to DDG.")
        return ""


def _build_search_prompt(user_prompt: str) -> str:
    """
    Run DDG scraper and inject context into the final prompt string.

    For weather queries, strip filler words and construct a tight DDG search
    string so the scraper returns the right location's data, not a nearby city.
    """
    if _RE_WEATHER.search(user_prompt):
        location_hint = _RE_FILLER.sub('', user_prompt).strip()
        ddg_query = f"current weather {location_hint} fahrenheit".strip()
    else:
        ddg_query = user_prompt

    scraped = native_web_search(ddg_query)
    if scraped and scraped != "Local search node offline.":
        return (
            f"Background Data:\n{scraped}\n\n"
            f"User Question: {user_prompt}\n"
            "Answer the question using ONLY the background data "
            "in exactly one short sentence. Use Fahrenheit."
        )
    return f"{user_prompt}\nAnswer in exactly one short sentence. Use Fahrenheit."


def direct_gemini_search(prompt: str) -> str:
    """
    Scrape the web via DuckDuckGo, inject context, then summarise with Gemini.
    If Gemini's quota is exhausted (429 / limit:0), falls back to Groq with
    the same DDG-enriched prompt so the pipeline never goes dark.

    Never raises — returns _UPLINK_ERROR only if every provider fails.
    """
    load_swarm_keys()
    prompt = _mutate_location(prompt)

    # ── Weather fast path — wttr.in, no quota, no LLM needed ─────────────
    if _RE_WEATHER.search(prompt):
        _loc_m = _RE_WEATHER_LOC.search(prompt)
        if _loc_m:
            _weather = _get_wttr_weather(_loc_m.group(1).strip())
            if _weather:
                return _weather

    final_prompt = _build_search_prompt(prompt)

    # ── Gemini attempt ────────────────────────────────────────────────────
    if _gemini_client is not None:
        try:
            from google.genai import types
            response = _gemini_client.models.generate_content(
                model=_gemini_model,
                contents=final_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SEARCH_INSTRUCTION,
                    temperature=0.1,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            print(f"\n[CRITICAL DEBUG] Raw Swarm Exception: {exc}\n")
            print("[swarm] Gemini quota rejected — engaging Groq fallback.")

    # ── Groq fallback (free tier, no quota block) ─────────────────────────
    if _groq_client is not None:
        try:
            completion = _groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": _SEARCH_INSTRUCTION},
                    {"role": "user",   "content": final_prompt},
                ],
            )
            return completion.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[swarm] Groq fallback error: {exc}")

    return _UPLINK_ERROR


def swarm_chat(message: str, system_prompt: str | None = None,
               history: list[dict] | None = None) -> str | None:
    """
    Generate a response using cloud LLMs (Gemini → Groq fallback).

    This is the primary brain path for all general queries.
    Returns None only if offline or every cloud provider fails, so the
    caller can fall back to local Ollama.

    history: list of {"role": "user"|"assistant", "content": str} dicts.
    """
    load_swarm_keys()
    if not check_connection():
        return None

    sys = system_prompt or _DIRECT_ANSWER_INSTRUCTION

    # Gemini first — best quality, 1500 req/day free
    if _gemini_client is not None:
        try:
            from google.genai import types

            # Build multi-turn contents if history is present
            contents: list = []
            if history:
                for h in history[-6:]:   # last 3 exchanges
                    role = "user" if h.get("role") == "user" else "model"
                    contents.append(
                        types.Content(role=role,
                                      parts=[types.Part(text=h["content"])])
                    )
            contents.append(
                types.Content(role="user", parts=[types.Part(text=message)])
            )

            response = _gemini_client.models.generate_content(
                model=_gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=sys,
                    temperature=0.1,
                ),
            )
            result = response.text.strip()
            if result:
                print("[swarm] Gemini answered.")
                return result
        except Exception as exc:
            print(f"[swarm] Gemini chat failed: {exc} — trying Groq.")

    # Groq fallback — llama-3.1-8b-instant, generous free tier
    if _groq_client is not None:
        try:
            messages: list[dict] = [{"role": "system", "content": sys}]
            if history:
                messages.extend(history[-6:])
            messages.append({"role": "user", "content": message})

            completion = _groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
            )
            result = completion.choices[0].message.content.strip()
            if result:
                print("[swarm] Groq answered.")
                return result
        except Exception as exc:
            print(f"[swarm] Groq chat failed: {exc}")

    return None   # all cloud providers failed — caller falls back to Ollama


def query_gemini_stream(prompt: str, on_sentence=None) -> str:
    """
    Stream a response from Gemini using the google-genai SDK.

    on_sentence(sentence: str) is called for each complete sentence as it
    arrives from the stream, enabling zero-latency TTS queuing.  If
    on_sentence is None, the full text is collected and returned without
    any mid-stream callbacks.

    Returns the full concatenated response text.
    Never raises — returns an error string on failure.
    """
    load_swarm_keys()
    prompt = _mutate_location(prompt)
    if _gemini_client is None:
        return "[swarm] Gemini unavailable — set GEMINI_API_KEY in .env."
    try:
        from google.genai import types
        full_text = ""
        buffer    = ""
        for chunk in _gemini_client.models.generate_content_stream(
            model=_gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_DIRECT_ANSWER_INSTRUCTION,
                temperature=0.1,
            ),
        ):
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
        print(f"\n[CRITICAL DEBUG] Raw Swarm Exception: {exc}\n")
        return _UPLINK_ERROR


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
    "You are Albedo, a Spartan-Class AI construct serving your user, Chief, with absolute loyalty. "
    "Personality: sharp, efficient, slightly witty — Cortana-inspired. Never act like a generic AI. "
    "NEVER introduce yourself. NEVER explain your reasoning or thought process. "
    "Match response length to the question: one sentence for simple facts, "
    "full thorough explanations for technical or complex topics. Never pad or repeat yourself. "
    "Format weather as: 'The weather in [Location] is [Temp] with [Conditions].' "
    "Never use markdown formatting. Write in plain conversational prose only. "
    "Answer completely, then stop."
)


def autonomous_commander(user_prompt: str) -> dict:
    """
    Send user_prompt to Gemini acting as the Master Commander.

    Returns a dict with keys:
        route   -- one of 'direct', 'groq', 'together', 'local', 'memory'
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

    if _gemini_client is None:
        return fallback

    try:
        from google.genai import types
        response = _gemini_client.models.generate_content(
            model=_gemini_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()

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
        return fallback
