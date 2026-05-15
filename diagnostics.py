"""
diagnostics.py  --  Tactical Hardware Audit

run_tactical_audit() pulls exact hardware specs, safely clears %TEMP%,
and returns a plain-prose SitRep string ready for the chat log and TTS.

All subsystems are individually guarded — a missing package or WMI
unavailability degrades gracefully rather than crashing the audit.

Dependencies: psutil, WMI (both auto-installed by setup_utility.py)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def run_tactical_audit() -> str:
    """
    Execute the full tactical audit and return a formatted SitRep string.
    Covers CPU, RAM, GPU, TEMP cleanup, and advisory recommendations.
    """
    lines: list[str] = [
        "TACTICAL HARDWARE AUDIT  //  SITREP",
        "=" * 44,
        "",
    ]

    # ── CPU ───────────────────────────────────────────────────────────────────
    cpu_name = _get_cpu_name()
    lines.append(f"CPU     : {cpu_name}")

    # ── RAM ───────────────────────────────────────────────────────────────────
    ram_str = _get_ram()
    lines.append(f"RAM     : {ram_str}")

    # ── GPU ───────────────────────────────────────────────────────────────────
    gpu_name = _get_gpu_name()
    lines.append(f"GPU     : {gpu_name}")

    lines.append("")

    # ── TEMP cleanup ──────────────────────────────────────────────────────────
    cleared_mb, skipped = _clear_temp()
    lines.append(
        f"TEMP    : Cleared {cleared_mb:.1f} MB  "
        f"({skipped} locked {'file' if skipped == 1 else 'files'} skipped)"
    )

    lines.append("")
    lines.append("ADVISORY:")
    lines.append(
        "  BIOS  --  Verify XMP / EXPO profile is active and matches your "
        "RAM kit's rated speed. A disabled XMP profile leaves DDR5 / DDR4 "
        "running at JEDEC base clocks."
    )
    lines.append(
        "  GPU   --  Review fan curves in MSI Afterburner or EVGA Precision X1. "
        "A flat 60 RPM% curve from 70 C keeps thermals stable under sustained load."
    )
    lines.append(
        "  THERMAL  --  Use HWiNFO64 for sustained thermal logging. "
        "Flag any sensor exceeding 85 C under full load for follow-up."
    )

    lines.append("")
    lines.append("Audit complete. Standing by for further directives, Chief.")

    return "\n".join(lines)


# ── Hardware collectors ───────────────────────────────────────────────────────

def _get_cpu_name() -> str:
    """Exact CPU name from WMI Win32_Processor, with psutil/platform fallback."""
    try:
        import wmi as _wmi
        c = _wmi.WMI()
        procs = c.Win32_Processor()
        if procs:
            return procs[0].Name.strip()
    except Exception:
        pass
    try:
        import platform
        name = platform.processor()
        if name:
            return name
    except Exception:
        pass
    return "Unknown CPU"


def _get_ram() -> str:
    """Total physical RAM in GB via psutil."""
    try:
        import psutil
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        return f"{total_gb:.1f} GB"
    except Exception:
        return "Unknown (psutil not available)"


def _get_gpu_name() -> str:
    """GPU model(s) from WMI Win32_VideoController."""
    try:
        import wmi as _wmi
        c = _wmi.WMI()
        controllers = c.Win32_VideoController()
        names = [g.Name.strip() for g in controllers if g.Name and g.Name.strip()]
        if names:
            return "  |  ".join(names)
    except Exception:
        pass
    return "Unknown GPU  --  install WMI for accurate GPU detection"


# ── TEMP cleaner ──────────────────────────────────────────────────────────────

def _clear_temp() -> tuple[float, int]:
    """
    Iterate %TEMP% and delete files / subdirectories, skipping anything
    locked by another process or protected by permissions.

    Returns (cleared_megabytes, skipped_count).
    """
    temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "")))
    if not temp_dir.is_dir():
        return 0.0, 0

    cleared_bytes = 0
    skipped = 0

    for entry in temp_dir.iterdir():
        try:
            if entry.is_file() or entry.is_symlink():
                size = entry.stat().st_size
                entry.unlink(missing_ok=True)
                cleared_bytes += size
            elif entry.is_dir():
                # Sum size before deletion so we can report it
                try:
                    size = sum(
                        f.stat().st_size
                        for f in entry.rglob("*")
                        if f.is_file()
                    )
                except Exception:
                    size = 0
                shutil.rmtree(entry, ignore_errors=False)
                cleared_bytes += size
        except Exception:
            skipped += 1

    return cleared_bytes / (1024 * 1024), skipped
