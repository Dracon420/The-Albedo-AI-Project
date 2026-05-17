"""
system_stats.py  --  Hardware detection helpers for the Albedo telemetry HUD.

Provides short, display-safe names for the host CPU and primary GPU, plus a
live GPU-load sampler.  All functions are safe to call from the main thread
at startup — they run quickly and never block longer than a few seconds.

CPU detection strategy (Windows):
  1. WMIC  -- subprocess call to `wmic cpu get Name /format:list`
  2. platform.processor() -- stdlib fallback (less clean, always works)
  The raw string is then shortened to a compact HUD label via regex so dials
  don't overflow: "AMD Ryzen 5 5600X 6-Core Processor" -> "Ryzen 5".

GPU detection strategy:
  1. GPUtil.getGPUs()[0].name -- primary dedicated GPU name
  2. "INTEGRATED" if GPUtil is installed but returns an empty list
  3. "SYS GPU" if GPUtil is not installed or raises
  VRAM load: gpus[0].load (0.0–1.0) -- actual GPU utilisation fraction.
"""
from __future__ import annotations

import re
import subprocess


# ---------------------------------------------------------------------------
# CPU name
# ---------------------------------------------------------------------------

_CPU_PATTERNS: list[tuple[re.Pattern, str]] = [
    # AMD Ryzen family
    (re.compile(r"Ryzen\s+(Threadripper|9|7|5|3)", re.I), lambda m: f"Ryzen {m.group(1).title()}"),
    # Intel Core family
    (re.compile(r"Core[^\s]?\s+(i\d)", re.I),             lambda m: f"Core {m.group(1).upper()}"),
    # Intel Xeon
    (re.compile(r"Xeon",              re.I),               lambda _: "Xeon"),
    # Intel Celeron / Pentium
    (re.compile(r"Celeron",           re.I),               lambda _: "Celeron"),
    (re.compile(r"Pentium",           re.I),               lambda _: "Pentium"),
    # Apple Silicon
    (re.compile(r"Apple\s+(M\d)",     re.I),               lambda m: f"Apple {m.group(1).upper()}"),
    # AMD Athlon / FX
    (re.compile(r"Athlon",            re.I),               lambda _: "Athlon"),
    (re.compile(r"\bFX[- ](\d+)",     re.I),               lambda m: f"FX-{m.group(1)}"),
]


def _shorten_cpu(raw: str) -> str:
    """Extract a compact HUD label from a raw processor name string."""
    for pattern, formatter in _CPU_PATTERNS:
        m = pattern.search(raw)
        if m:
            result = formatter(m) if callable(formatter) else formatter
            return result[:12]  # hard cap so it fits under a 120px dial
    # Last resort: first two words, capped
    words = raw.strip().split()
    return " ".join(words[:2])[:12] if words else "CPU"


def get_cpu_name() -> str:
    """
    Return a short CPU model label for the telemetry HUD.
    Never raises — falls back through strategies until something works.
    """
    # Strategy 1: PowerShell Get-WmiObject — works on Windows 11 where
    # the deprecated wmic.exe may not be on PATH.
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Class Win32_Processor).Name"],
            capture_output=True, text=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        raw = result.stdout.strip()
        if raw and result.returncode == 0:
            return _shorten_cpu(raw)
    except Exception:
        pass

    # Strategy 2: WMIC (older Windows builds)
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "Name", "/format:list"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            if line.upper().startswith("NAME="):
                raw = line.split("=", 1)[1].strip()
                if raw:
                    return _shorten_cpu(raw)
    except Exception:
        pass

    # Strategy 3: platform.processor() — stdlib, cross-platform
    try:
        import platform
        raw = platform.processor().strip()
        if raw and raw != "AMD64":
            return _shorten_cpu(raw)
    except Exception:
        pass

    return "CPU"


# ---------------------------------------------------------------------------
# GPU name and load
# ---------------------------------------------------------------------------

_GPU_STRIP = re.compile(
    r"\b(NVIDIA|AMD|Intel|GeForce|Radeon|Graphics|GPU)\b\s*", re.I
)


def _nvml_query(fields: str) -> list[str] | None:
    """
    Run nvidia-smi with CREATE_NO_WINDOW so no console flashes on screen.
    Returns a list of stripped field values, or None on any error.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [v.strip() for v in result.stdout.strip().split(",")]
    except Exception:
        pass
    return None


def get_gpu_name() -> str:
    """
    Return a short GPU model label for the telemetry HUD.
    Uses nvidia-smi (no subprocess window); falls back to "SYS GPU".
    """
    vals = _nvml_query("name")
    if vals:
        name = vals[0]
        name = _GPU_STRIP.sub("", name).strip()
        return name[:12] if name else "SYS GPU"
    return "SYS GPU"


def get_gpu_load() -> float:
    """
    Return GPU utilisation as a 0.0–1.0 fraction.
    Uses nvidia-smi with CREATE_NO_WINDOW — no console flash.
    Returns 0.0 on any error so the dial simply shows empty rather than crashing.
    """
    vals = _nvml_query("utilization.gpu")
    if vals:
        try:
            return float(vals[0]) / 100.0
        except ValueError:
            pass
    return 0.0
