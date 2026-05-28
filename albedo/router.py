"""
Albedo Meta-Router — classify queries and dispatch to the optimal agent.

Route priority (applied after all deterministic interceptors in pipeline.py):

  TECH  — code, programming, microcontrollers, electronics, wiring, firmware
           → albedo-jarvis-tech  (Qwen2.5-Coder-7B)

  JARVIS — strategic analysis, mission planning, comparisons, pros/cons,
            engineering depth, "brief me on", "what's the best approach"
            → albedo-jarvis-8b  (fine-tuned JARVIS personality)

  DEFAULT — everything else → whichever persona fired the wake word
            (cortana-8b by default, jarvis-8b if "jarvis" was the wake word)

The router does NOT replace persona routing for Cortana/JARVIS queries — it
only overrides when a specialist agent would clearly outperform the active
persona. A general Cortana-flavoured question always stays with Cortana.
"""

from __future__ import annotations

import re

# ── Route constants ────────────────────────────────────────────────────────────
ROUTE_TECH    = "tech"
ROUTE_JARVIS  = "jarvis"
ROUTE_DEFAULT = "default"

# ── Code / programming signals ─────────────────────────────────────────────────
_CODE_KEYWORDS = frozenset({
    # Languages / runtimes
    "python", "javascript", "typescript", "rust", "c++", "c#", "golang", "java",
    "bash", "powershell", "sql", "html", "css", "json", "yaml", "xml",
    # Actions
    "write a", "write me", "code a", "code me", "implement", "debug",
    "fix this code", "fix the bug", "fix this bug", "refactor", "optimize this",
    "unit test", "write tests", "write a test", "parse", "regex", "function",
    "class", "script", "algorithm", "data structure", "api endpoint",
    "async", "await", "coroutine", "decorator", "lambda", "recursion",
    "loop", "iterate", "sort", "filter", "map", "reduce",
    # Dev tooling
    "git", "docker", "dockerfile", "docker-compose", "kubernetes", "k8s",
    "pip install", "npm install", "poetry", "venv", "conda",
    "makefile", "cmake", "build system", "ci/cd", "github actions",
    # Errors
    "traceback", "exception", "syntax error", "runtime error", "import error",
    "stack overflow", "null pointer", "index out of range", "segfault",
    "memory leak", "race condition", "deadlock",
})

_CODE_RE = re.compile(
    r'\bcode\b|\bscript\b|\bfunction\b|\bclass\b|\bmodule\b|\bpackage\b'
    r'|\bprogram\b|\bapplication\b|\bapp\b'
    r'|\bwrite\s+(?:a\s+)?(?:function|class|script|program|code|module)'
    r'|\bfix\s+(?:this\s+)?(?:code|bug|error|crash|exception|issue)'
    r'|\bhow\s+(?:do\s+I|to)\s+(?:code|program|write|implement|build|make)',
    re.IGNORECASE,
)

# ── Electronics / embedded / IoT signals ──────────────────────────────────────
_HARDWARE_TECH_KEYWORDS = frozenset({
    # Microcontrollers
    "esp32", "esp8266", "arduino", "raspberry pi", "rpi", "stm32", "attiny",
    "microcontroller", "mcu", "firmware", "flash", "bootloader",
    # Protocols / buses
    "i2c", "spi", "uart", "gpio", "pwm", "adc", "dac",
    "mqtt", "esphome", "home assistant", "homeassistant",
    "modbus", "can bus", "rs485", "rs232", "one-wire", "onewire",
    # Sensors / actuators
    "sensor", "relay", "servo", "stepper motor", "stepper", "encoder",
    "accelerometer", "gyroscope", "imu", "barometer", "thermistor",
    "dht22", "dht11", "bme280", "bmp280", "ds18b20", "hx711", "ina219",
    "neopixel", "ws2812", "led strip", "oled", "lcd display",
    # Electronics
    "circuit", "schematic", "pcb", "breadboard", "capacitor", "resistor",
    "transistor", "mosfet", "voltage divider", "pull-up", "pull-down",
    "wiring diagram", "pinout", "datasheet",
    # 3D printing electronics
    "klipper", "marlin", "ender", "cr-10", "hotend", "thermistor",
    "extruder", "stepper driver", "tmc2209", "tmc2208",
})

# ── Strategic / analysis signals ──────────────────────────────────────────────
_STRATEGIC_KEYWORDS = frozenset({
    "best approach", "best strategy", "best way to", "what's the best",
    "pros and cons", "pros cons", "tradeoffs", "trade-offs", "trade offs",
    "compare", "comparison", "versus", " vs ", "vs.", "which is better",
    "should i use", "should i choose", "should i go with",
    "brief me", "briefing", "mission brief", "situation report", "sitrep",
    "analysis", "analyze", "analyse", "assess", "assessment",
    "recommend", "recommendation", "advise", "advice on",
    "architecture", "design pattern", "system design",
    "risk", "risks", "mitigation", "contingency", "fallback plan",
    "strategic", "tactically", "operationally",
    "break down", "deep dive", "explain in depth", "walk me through",
    "what are my options", "what are the options",
})

_STRATEGIC_RE = re.compile(
    r'\bwhat\s+(?:is\s+the\s+)?best\s+(?:way|approach|strategy|method|option)\b'
    r'|\bshould\s+I\s+(?:use|pick|choose|go\s+with|build|deploy)\b'
    r'|\bcompare\s+\w+\s+(?:and|vs\.?|versus)\s+\w+'
    r'|\bpros?\s+and\s+cons?\b'
    r'|\bbrief\s+me\b|\bmission\s+brief\b',
    re.IGNORECASE,
)


# ── Public API ─────────────────────────────────────────────────────────────────

def classify(query: str) -> str:
    """
    Return one of ROUTE_TECH, ROUTE_JARVIS, or ROUTE_DEFAULT.

    Called from pipeline.py after all deterministic interceptors (Wolfram,
    audit, launch, kill, download) have already had their chance.

    Strategy:
      1. Check for embedded code blocks — immediate TECH route.
      2. Keyword scan for code/electronics → TECH.
      3. Pattern/keyword scan for strategic analysis → JARVIS.
      4. Fallback → DEFAULT (active persona handles it).
    """
    q_lower = query.lower()

    # ── 1. Embedded code block → always TECH ──────────────────────────────
    if "```" in query or "`" in query:
        return ROUTE_TECH

    # ── 2. Code / electronics keyword match ───────────────────────────────
    if any(kw in q_lower for kw in _CODE_KEYWORDS):
        return ROUTE_TECH
    if any(kw in q_lower for kw in _HARDWARE_TECH_KEYWORDS):
        return ROUTE_TECH
    if _CODE_RE.search(query):
        return ROUTE_TECH

    # ── 3. Strategic / analysis ───────────────────────────────────────────
    if any(kw in q_lower for kw in _STRATEGIC_KEYWORDS):
        return ROUTE_JARVIS
    if _STRATEGIC_RE.search(query):
        return ROUTE_JARVIS

    # ── 4. Default — let the active persona handle it ─────────────────────
    return ROUTE_DEFAULT
