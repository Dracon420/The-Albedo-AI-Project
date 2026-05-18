"""
hardware_profile.py — first-boot hardware detection with on-disk cache.

Heavy WMI queries (CPU name, GPU name, total RAM, total VRAM) only need to
run once per installation. This module probes the host via PowerShell/WMI +
nvidia-smi + psutil on the first boot, caches the cleaned results to
``hardware_config.json`` next to the install root, and serves the cache on
every subsequent call.

Public API:
    get_hardware(force_refresh=False) -> dict
    cpu_short() -> str            # short HUD label
    gpu_short() -> str
    ram_gb() -> float
    vram_mb() -> int
    cache_path() -> Path

Cache schema (hardware_config.json):
    {
      "schema_version": 1,
      "cached_at": "2026-05-17T22:30:00",
      "cpu":      { "raw": str, "short": str, "cores_physical": int, "cores_logical": int },
      "gpu":      { "raw": str, "short": str, "vram_mb": int },
      "ram":      { "total_gb": float },
      "platform": { "system": str, "release": str, "version": str, "machine": str }
    }

Designed to never raise during boot — every probe has a guarded fallback
so a missing tool (no nvidia-smi, no PowerShell, no psutil) just yields
the safest defaults.
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path

_ROOT       = Path(__file__).resolve().parent.parent
_CACHE_FILE = _ROOT / "hardware_config.json"
_SCHEMA     = 1

# Subprocess hide-window flag — Windows only; benign no-op on other OSes.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW   # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0


# ---------------------------------------------------------------------------
# Internal: CPU label shortener (same family logic as system_stats._shorten_cpu)
# ---------------------------------------------------------------------------

_CPU_PATTERNS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"Ryzen\s+(Threadripper|9|7|5|3)", re.I),
        lambda m: f"Ryzen {m.group(1).title()}"),
    (re.compile(r"Core[^\s]?\s+(i\d)", re.I),
        lambda m: f"Core {m.group(1).upper()}"),
    (re.compile(r"Xeon", re.I),    lambda _: "Xeon"),
    (re.compile(r"Celeron", re.I), lambda _: "Celeron"),
    (re.compile(r"Pentium", re.I), lambda _: "Pentium"),
    (re.compile(r"Apple\s+(M\d)", re.I),
        lambda m: f"Apple {m.group(1).upper()}"),
    (re.compile(r"Athlon", re.I),  lambda _: "Athlon"),
    (re.compile(r"\bFX[- ](\d+)", re.I),
        lambda m: f"FX-{m.group(1)}"),
]

_GPU_STRIP = re.compile(
    r"\b(NVIDIA|AMD|Intel|GeForce|Radeon|Graphics|GPU)\b\s*", re.I
)


def _shorten_cpu(raw: str) -> str:
    for pattern, formatter in _CPU_PATTERNS:
        m = pattern.search(raw)
        if m:
            result = formatter(m) if callable(formatter) else formatter
            return result[:12]
    words = raw.strip().split()
    return " ".join(words[:2])[:12] if words else "CPU"


def _shorten_gpu(raw: str) -> str:
    cleaned = _GPU_STRIP.sub("", raw).strip()
    return cleaned[:12] if cleaned else "SYS GPU"


# ---------------------------------------------------------------------------
# Probes — each returns a safe partial dict, never raises
# ---------------------------------------------------------------------------

def _probe_cpu() -> dict:
    raw = ""
    # PowerShell WMI first (works on Win 11 where wmic.exe may be absent)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Class Win32_Processor).Name"],
            capture_output=True, text=True, timeout=8,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip():
            raw = r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    if not raw:
        try:
            r = subprocess.run(
                ["wmic", "cpu", "get", "Name", "/format:list"],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            for line in r.stdout.splitlines():
                if line.upper().startswith("NAME="):
                    raw = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass

    if not raw:
        try:
            p = platform.processor().strip()
            if p and p != "AMD64":
                raw = p
        except Exception:
            pass

    cores_physical = cores_logical = 0
    try:
        import psutil
        cores_physical = psutil.cpu_count(logical=False) or 0
        cores_logical  = psutil.cpu_count(logical=True)  or 0
    except Exception:
        pass

    return {
        "raw":            raw or "Unknown CPU",
        "short":          _shorten_cpu(raw) if raw else "CPU",
        "cores_physical": cores_physical,
        "cores_logical":  cores_logical,
    }


def _probe_gpu() -> dict:
    raw = ""
    vram_mb = 0
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 1:
                raw = parts[0]
            if len(parts) >= 2:
                try:
                    vram_mb = int(parts[1])
                except ValueError:
                    pass
    except Exception:
        pass

    return {
        "raw":     raw or "No discrete GPU",
        "short":   _shorten_gpu(raw) if raw else "SYS GPU",
        "vram_mb": vram_mb,
    }


def _probe_ram() -> dict:
    total_gb = 0.0
    try:
        import psutil
        total_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass
    return {"total_gb": total_gb}


def _probe_platform() -> dict:
    try:
        return {
            "system":  platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        }
    except Exception:
        return {"system": "", "release": "", "version": "", "machine": ""}


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def _load_cache() -> dict | None:
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema_version") == _SCHEMA:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _save_cache(data: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _build_fresh() -> dict:
    return {
        "schema_version": _SCHEMA,
        "cached_at":      datetime.now().isoformat(timespec="seconds"),
        "cpu":            _probe_cpu(),
        "gpu":            _probe_gpu(),
        "ram":            _probe_ram(),
        "platform":       _probe_platform(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hardware(force_refresh: bool = False) -> dict:
    """
    Return the full hardware profile, building and caching it on first call.

    Subsequent calls read the cache and return instantly.
    Pass ``force_refresh=True`` to re-probe and overwrite the cache (useful
    after a hardware change like a new GPU).
    """
    if not force_refresh:
        cached = _load_cache()
        if cached is not None:
            return cached

    fresh = _build_fresh()
    _save_cache(fresh)
    return fresh


def cpu_short() -> str:
    return get_hardware().get("cpu", {}).get("short", "CPU")


def gpu_short() -> str:
    return get_hardware().get("gpu", {}).get("short", "SYS GPU")


def ram_gb() -> float:
    return get_hardware().get("ram", {}).get("total_gb", 0.0)


def vram_mb() -> int:
    return get_hardware().get("gpu", {}).get("vram_mb", 0)


def cache_path() -> Path:
    return _CACHE_FILE
