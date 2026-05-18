"""
telemetry.py — live host telemetry with delta-based throughput calculations.

Provides a single ``get_full_telemetry()`` entry point that returns a flat,
JSON-serializable dict describing the current state of the host: CPU load
and frequency, RAM usage, GPU load + VRAM + temperature, disk read/write
throughput in MB/s, and network upload/download throughput in Mbps.

The throughput numbers (disk + network) require state between calls — psutil
exposes cumulative byte counters, so this module remembers the last reading
and computes the delta against wall-clock time. On the very first call the
deltas are zero (we have no baseline yet). On every subsequent call they
reflect the rate since the previous call.

Thread-safe: a single Lock guards the shared delta state so a UI poller
and an Eel RPC handler can both call ``get_full_telemetry()`` without
corrupting each other's baselines.

Designed for use by:
  - The current Tkinter HUD (replaces the cobbled-together psutil calls
    scattered through gui.py)
  - The forthcoming Eel SVG ring widgets (Phase 2) — call frequency 1-4 Hz

Public API
----------
    get_full_telemetry() -> dict
    reset() -> None                 -- discard cached deltas (testing)

Schema (every key always present, defaults are 0 / 0.0 / False when probe fails):

    {
      "ts":      ISO-8601 timestamp,
      "cpu": {
          "percent":       float 0-100,
          "freq_ghz":      float,             # current core frequency
          "cores_logical": int
      },
      "ram": {
          "used_gb":  float,
          "total_gb": float,
          "percent":  float 0-100
      },
      "gpu": {
          "available":    bool,               # False if nvidia-smi missing
          "load_percent": float 0-100,
          "vram_used_mb": int,
          "vram_total_mb": int,
          "vram_percent": float 0-100,
          "temp_c":       int                 # current core temperature
      },
      "disk": {
          "read_mb_s":      float,            # delta-based, MB/s
          "write_mb_s":     float,
          "percent_used_c": float 0-100       # fill level of C:
      },
      "network": {
          "down_mbps": float,                 # delta-based, Mbps
          "up_mbps":   float
      }
    }
"""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

# Hidden-window flag — Windows only, no-op elsewhere.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW   # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0


# ---------------------------------------------------------------------------
# Shared delta state (guarded by _LOCK)
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()

# Last sample: (timestamp_seconds, bytes_sent, bytes_recv) for network
_last_net: Optional[tuple[float, int, int]] = None

# Last sample: (timestamp_seconds, read_bytes, write_bytes) for disk
_last_disk: Optional[tuple[float, int, int]] = None


def reset() -> None:
    """Discard the cached baselines so the next call starts fresh."""
    global _last_net, _last_disk
    with _LOCK:
        _last_net = None
        _last_disk = None


# ---------------------------------------------------------------------------
# nvidia-smi multi-field query (shared with system_stats.py — duplicated
# here so this module has no internal dependencies beyond psutil)
# ---------------------------------------------------------------------------

def _nvml_multi(fields: str) -> Optional[list[str]]:
    """Single nvidia-smi call requesting multiple comma-separated fields."""
    try:
        r = subprocess.run(
            ["nvidia-smi",
             f"--query-gpu={fields}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip():
            # Take only the first GPU row to keep schema flat.
            first = r.stdout.strip().splitlines()[0]
            return [v.strip() for v in first.split(",")]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Probe helpers — each returns a complete subdict with safe defaults
# ---------------------------------------------------------------------------

def _probe_cpu(psutil) -> dict:
    out = {"percent": 0.0, "freq_ghz": 0.0, "cores_logical": 0}
    try:
        out["percent"] = float(psutil.cpu_percent(interval=None))
    except Exception:
        pass
    try:
        freq = psutil.cpu_freq()
        if freq and freq.current:
            # psutil returns MHz on Windows, sometimes GHz on macOS.
            mhz = float(freq.current)
            out["freq_ghz"] = round(mhz / 1000.0, 2) if mhz > 100 else round(mhz, 2)
    except Exception:
        pass
    try:
        out["cores_logical"] = int(psutil.cpu_count(logical=True) or 0)
    except Exception:
        pass
    return out


def _probe_ram(psutil) -> dict:
    out = {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}
    try:
        mem = psutil.virtual_memory()
        gb = 1024 ** 3
        out["used_gb"]  = round(mem.used / gb, 2)
        out["total_gb"] = round(mem.total / gb, 2)
        out["percent"]  = float(mem.percent)
    except Exception:
        pass
    return out


def _probe_gpu() -> dict:
    out = {
        "available": False,
        "load_percent": 0.0,
        "vram_used_mb": 0,
        "vram_total_mb": 0,
        "vram_percent": 0.0,
        "temp_c": 0,
    }
    vals = _nvml_multi("utilization.gpu,memory.used,memory.total,temperature.gpu")
    if not vals or len(vals) < 4:
        return out
    out["available"] = True
    try:
        out["load_percent"] = float(vals[0])
    except ValueError:
        pass
    try:
        out["vram_used_mb"]  = int(float(vals[1]))
        out["vram_total_mb"] = int(float(vals[2]))
        if out["vram_total_mb"] > 0:
            out["vram_percent"] = round(
                100.0 * out["vram_used_mb"] / out["vram_total_mb"], 1)
    except ValueError:
        pass
    try:
        out["temp_c"] = int(float(vals[3]))
    except ValueError:
        pass
    return out


def _probe_disk(psutil, now: float) -> dict:
    """Delta-based disk throughput plus the C: fill percentage."""
    global _last_disk
    out = {"read_mb_s": 0.0, "write_mb_s": 0.0, "percent_used_c": 0.0}

    try:
        io = psutil.disk_io_counters()
    except Exception:
        io = None

    if io is not None:
        prev = _last_disk
        _last_disk = (now, io.read_bytes, io.write_bytes)
        if prev is not None:
            dt = now - prev[0]
            if dt > 0:
                mb = 1024 ** 2
                # Guard against counter resets (negative delta) — return 0
                # rather than a huge negative number that would tank the UI.
                dr = max(0, io.read_bytes  - prev[1])
                dw = max(0, io.write_bytes - prev[2])
                out["read_mb_s"]  = round((dr / dt) / mb, 2)
                out["write_mb_s"] = round((dw / dt) / mb, 2)

    try:
        out["percent_used_c"] = float(psutil.disk_usage("C:\\").percent)
    except Exception:
        pass

    return out


def _probe_network(psutil, now: float) -> dict:
    """Delta-based network throughput in Mbps (megabits per second)."""
    global _last_net
    out = {"down_mbps": 0.0, "up_mbps": 0.0}

    try:
        net = psutil.net_io_counters()
    except Exception:
        return out

    prev = _last_net
    _last_net = (now, net.bytes_sent, net.bytes_recv)
    if prev is not None:
        dt = now - prev[0]
        if dt > 0:
            # bytes/s → bits/s → Mbps  ==  bytes * 8 / 1_000_000 / dt
            # Use 1_000_000 (decimal mega) for network — ISP convention.
            up_b   = max(0, net.bytes_sent - prev[1])
            down_b = max(0, net.bytes_recv - prev[2])
            out["up_mbps"]   = round((up_b   * 8) / 1_000_000 / dt, 2)
            out["down_mbps"] = round((down_b * 8) / 1_000_000 / dt, 2)

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_full_telemetry() -> dict:
    """
    Sample every channel once and return a single JSON-serializable dict.

    Throughput numbers (disk read/write, network up/down) are calculated
    from the delta since the previous call to this function — so the *rate*
    you see is "what happened between the last call and now". The first
    call after import (or after reset()) returns zeros for those rates;
    every subsequent call returns the real rate.

    All other fields (CPU %, RAM, GPU load/VRAM/temp, disk fill) are
    instantaneous snapshots and don't depend on previous state.

    Designed to be called by a UI poller at 1-4 Hz. Total cost is dominated
    by the nvidia-smi subprocess (~50-150 ms); psutil calls are sub-ms.
    """
    # Defer psutil import so a missing install doesn't break module load
    try:
        import psutil
    except ImportError:
        # Return an all-zeros payload so the UI at least has a complete shape.
        now_iso = datetime.now().isoformat(timespec="seconds")
        return {
            "ts":      now_iso,
            "cpu":     {"percent": 0.0, "freq_ghz": 0.0, "cores_logical": 0},
            "ram":     {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0},
            "gpu":     _probe_gpu(),
            "disk":    {"read_mb_s": 0.0, "write_mb_s": 0.0, "percent_used_c": 0.0},
            "network": {"down_mbps": 0.0, "up_mbps": 0.0},
        }

    now_mono = time.monotonic()
    with _LOCK:
        snapshot = {
            "ts":      datetime.now().isoformat(timespec="seconds"),
            "cpu":     _probe_cpu(psutil),
            "ram":     _probe_ram(psutil),
            "gpu":     _probe_gpu(),
            "disk":    _probe_disk(psutil, now_mono),
            "network": _probe_network(psutil, now_mono),
        }
    return snapshot
