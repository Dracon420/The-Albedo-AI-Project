"""
Unit tests for albedo.telemetry — focuses on the stateful delta math
since that's where the bugs hide. Probe values are mocked so the tests
are fast and deterministic, independent of the host's actual hardware.

Run:
    python -m pytest tests/test_telemetry.py -v

(falls back to argv-driven invocation when pytest isn't available)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Make the repo root importable when running as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from albedo import telemetry   # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_psutil(net_sent=0, net_recv=0, disk_read=0, disk_write=0,
                 cpu_pct=0.0, ram_used=0, ram_total=16 * 1024 ** 3,
                 ram_pct=0.0, disk_c_pct=0.0,
                 freq_mhz=3600.0, cores=12):
    """Build a minimal psutil stand-in with deterministic counter values."""
    return SimpleNamespace(
        net_io_counters=lambda: SimpleNamespace(
            bytes_sent=net_sent, bytes_recv=net_recv),
        disk_io_counters=lambda: SimpleNamespace(
            read_bytes=disk_read, write_bytes=disk_write),
        cpu_percent=lambda interval=None: cpu_pct,
        cpu_freq=lambda: SimpleNamespace(current=freq_mhz, min=0, max=0),
        cpu_count=lambda logical=True: cores,
        virtual_memory=lambda: SimpleNamespace(
            used=ram_used, total=ram_total, percent=ram_pct),
        disk_usage=lambda path: SimpleNamespace(percent=disk_c_pct),
    )


# ---------------------------------------------------------------------------
# Delta math
# ---------------------------------------------------------------------------

def test_first_call_returns_zero_throughput():
    """No baseline yet → rates must be 0, never NaN or huge numbers."""
    telemetry.reset()
    ps = _fake_psutil(net_sent=1_000_000, net_recv=2_000_000,
                      disk_read=500_000, disk_write=300_000)
    with patch.dict(sys.modules, {"psutil": ps}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        snap = telemetry.get_full_telemetry()
    assert snap["network"]["down_mbps"] == 0.0
    assert snap["network"]["up_mbps"]   == 0.0
    assert snap["disk"]["read_mb_s"]    == 0.0
    assert snap["disk"]["write_mb_s"]   == 0.0


def test_second_call_computes_real_throughput():
    """1 second elapsed, +1 MB net received → ~8 Mbps down (1 MB = 8 Mbits)."""
    telemetry.reset()
    times = iter([1000.0, 1001.0])  # 1 second apart

    # Call 1: seed baseline at t=1000, no counters moving yet
    ps_a = _fake_psutil(net_recv=10_000_000, disk_read=20_000_000)
    with patch("time.monotonic", lambda: next(times)), \
         patch.dict(sys.modules, {"psutil": ps_a}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        telemetry.get_full_telemetry()

    # Call 2: +1 MB downloaded, +5 MB read → at 1 s elapsed
    ps_b = _fake_psutil(net_recv=10_000_000 + 1_000_000,
                        disk_read=20_000_000 + 5 * 1024 * 1024)
    with patch("time.monotonic", lambda: next(times)), \
         patch.dict(sys.modules, {"psutil": ps_b}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        snap = telemetry.get_full_telemetry()

    # 1 MB/s × 8 / 1_000_000 (decimal mega) = 8 Mbps
    assert snap["network"]["down_mbps"] == 8.0
    # Disk uses binary MB (1024^2), so 5 MiB / 1 s = 5 MB/s
    assert snap["disk"]["read_mb_s"] == 5.0


def test_counter_reset_returns_zero_not_negative():
    """Some Windows builds reset disk/net counters → must not produce negatives."""
    telemetry.reset()
    times = iter([2000.0, 2001.0])

    # Call 1: high baseline
    ps_a = _fake_psutil(net_recv=10_000_000_000, disk_read=10_000_000_000)
    with patch("time.monotonic", lambda: next(times)), \
         patch.dict(sys.modules, {"psutil": ps_a}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        telemetry.get_full_telemetry()

    # Call 2: counters dropped to zero (process restart, etc.)
    ps_b = _fake_psutil(net_recv=0, disk_read=0)
    with patch("time.monotonic", lambda: next(times)), \
         patch.dict(sys.modules, {"psutil": ps_b}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        snap = telemetry.get_full_telemetry()

    assert snap["network"]["down_mbps"] == 0.0
    assert snap["disk"]["read_mb_s"]    == 0.0


def test_schema_is_always_complete():
    """Every documented key must be present even when every probe fails."""
    telemetry.reset()
    # Force psutil import to fail so we exercise the fallback branch.
    with patch.dict(sys.modules, {"psutil": None}):
        snap = telemetry.get_full_telemetry()
    for key in ("ts", "cpu", "ram", "gpu", "disk", "network"):
        assert key in snap, f"missing top-level key: {key}"
    for k in ("percent", "freq_ghz", "cores_logical"):
        assert k in snap["cpu"]
    for k in ("used_gb", "total_gb", "percent"):
        assert k in snap["ram"]
    for k in ("available", "load_percent", "vram_used_mb", "vram_total_mb",
              "vram_percent", "temp_c"):
        assert k in snap["gpu"]
    for k in ("read_mb_s", "write_mb_s", "percent_used_c"):
        assert k in snap["disk"]
    for k in ("down_mbps", "up_mbps"):
        assert k in snap["network"]


def test_gpu_probe_parses_nvidia_smi_csv():
    telemetry.reset()
    ps = _fake_psutil()
    fake_smi = ["35", "2048", "6144", "62"]    # load, vram_used, vram_total, temp
    with patch.dict(sys.modules, {"psutil": ps}), \
         patch.object(telemetry, "_nvml_multi", return_value=fake_smi):
        snap = telemetry.get_full_telemetry()
    g = snap["gpu"]
    assert g["available"]      is True
    assert g["load_percent"]   == 35.0
    assert g["vram_used_mb"]   == 2048
    assert g["vram_total_mb"]  == 6144
    assert g["vram_percent"]   == 33.3
    assert g["temp_c"]         == 62


def test_gpu_unavailable_when_nvidia_smi_returns_none():
    telemetry.reset()
    ps = _fake_psutil()
    with patch.dict(sys.modules, {"psutil": ps}), \
         patch.object(telemetry, "_nvml_multi", return_value=None):
        snap = telemetry.get_full_telemetry()
    assert snap["gpu"]["available"]    is False
    assert snap["gpu"]["load_percent"] == 0.0
    assert snap["gpu"]["temp_c"]       == 0


# ---------------------------------------------------------------------------
# Lightweight standalone runner so this also works without pytest installed
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect, traceback
    mod = sys.modules[__name__]
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
