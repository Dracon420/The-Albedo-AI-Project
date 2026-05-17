"""
diagnostics.py  --  Tactical Hardware Audit

run_tactical_audit() pulls exact hardware specs, live thermals, disk usage,
and safely clears %TEMP%. Returns a plain-prose SitRep ready for the chat log
and TTS. Also exposes get_hardware_summary() for injecting specs into LLM
prompts (e.g. overclocking guidance).

All subsystems are individually guarded — a missing package or WMI
unavailability degrades gracefully rather than crashing the audit.

Dependencies: psutil, WMI (both auto-installed by setup_utility.py)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def run_tactical_audit() -> str:
    """Full tactical audit — hardware, thermals, disk, temp cleanup, advisories."""
    lines: list[str] = [
        "TACTICAL HARDWARE AUDIT  //  SITREP",
        "=" * 44,
        "",
    ]

    lines.append(f"CPU     : {_get_cpu_name()}")
    lines.append(f"CORES   : {_get_cpu_cores()}")
    lines.append(f"SPEED   : {_get_cpu_freq()}")
    lines.append(f"RAM     : {_get_ram()}")
    lines.append(f"GPU     : {_get_gpu_name()}")
    lines.append(f"VRAM    : {_get_vram()}")
    lines.append("")

    lines.append("THERMALS:")
    for label, temp in _get_temperatures():
        lines.append(f"  {label:<20}: {temp}°C")

    lines.append("")
    lines.append("STORAGE:")
    for drive_line in _get_disk_usage():
        lines.append(f"  {drive_line}")

    lines.append("")
    cleared_mb, skipped = _clear_temp()
    lines.append(
        f"TEMP    : Cleared {cleared_mb:.1f} MB  "
        f"({skipped} locked {'file' if skipped == 1 else 'files'} skipped)"
    )

    lines.append("")
    lines.append("TOP PROCESSES (RAM):")
    for p in _get_top_processes(5):
        lines.append(f"  {p}")

    lines.append("")
    lines.append("ADVISORY:")
    lines.append(
        "  BIOS  --  Verify XMP / EXPO profile is active and matches your "
        "RAM kit's rated speed."
    )
    lines.append(
        "  GPU   --  Review fan curves in MSI Afterburner. "
        "A 60% fan from 70C keeps thermals stable under sustained load."
    )
    lines.append(
        "  THERMAL  --  Use HWiNFO64 for sustained thermal logging. "
        "Flag any sensor exceeding 85C under full load for follow-up."
    )
    lines.append("")
    lines.append("Audit complete. Standing by for further directives, Chief.")

    return "\n".join(lines)


def get_spoken_audit() -> str:
    """
    Natural-language prose version of the tactical audit, designed for TTS.
    No symbols, no table formatting — just sentences Albedo can speak naturally.
    """
    cpu   = _get_cpu_name()
    cores = _get_cpu_cores()
    freq  = _get_cpu_freq()
    ram   = _get_ram()
    gpu   = _get_gpu_name()
    vram  = _get_vram()

    lines: list[str] = []
    lines.append(
        f"Your system is running a {cpu}, with {cores} and a clock speed of {freq}."
    )
    lines.append(f"You have {ram} of system memory.")
    lines.append(f"Your graphics card is the {gpu} with {vram} of video memory.")

    temps = _get_temperatures()
    if temps:
        temp_parts = [f"{label.strip()} at {t} degrees" for label, t in temps[:4]]
        lines.append("Current thermals: " + ", ".join(temp_parts) + ".")
    else:
        lines.append("Thermal sensor data is unavailable on this system.")

    disks = _get_disk_usage()
    if disks and disks[0] != "Disk info unavailable":
        spoken_disks = []
        for d in disks:
            # "C:\  476 GB total  244 GB used  232 GB free  (51%)"
            # → "Drive C: 476 GB total, 244 GB used, 232 GB free"
            clean = d.replace("\\", "").strip()
            # "C:  476 GB total ..." → "Drive C: 476 GB total ..."
            import re as _re
            clean = _re.sub(r'^([A-Z]):\s*', r'Drive \1: ', clean)
            clean = _re.sub(r'\s{2,}', ', ', clean)
            clean = _re.sub(r'\((\d+)%\)', r'at \1 percent capacity', clean)
            spoken_disks.append(clean)
        lines.append("Storage: " + ".  ".join(spoken_disks) + ".")

    cleared_mb, skipped = _clear_temp()
    lines.append(
        f"I cleared {cleared_mb:.0f} megabytes of temporary files"
        + (f", with {skipped} locked files skipped." if skipped else ".")
    )

    top = _get_top_processes(3)
    if top and top[0] != "Process info unavailable":
        proc_names = [
            p.split()[0].removesuffix(".exe").removesuffix(".EXE")
            for p in top
        ]
        lines.append(
            "Your top memory consumers are: " + ", ".join(proc_names) + "."
        )

    lines.append(
        "Advisory: confirm your XMP or EXPO profile is active in BIOS for full RAM speed. "
        "Review your GPU fan curve in MSI Afterburner, and flag any sensor above 85 degrees "
        "under load for follow-up."
    )
    lines.append("Audit complete. Standing by, Chief.")

    return "  ".join(lines)


def get_hardware_summary() -> str:
    """
    Compact one-paragraph hardware description for injecting into LLM prompts.
    Used by overclocking and optimization query paths.
    """
    cpu   = _get_cpu_name()
    cores = _get_cpu_cores()
    freq  = _get_cpu_freq()
    ram   = _get_ram()
    gpu   = _get_gpu_name()
    vram  = _get_vram()
    disks = ";  ".join(_get_disk_usage())
    temps = ",  ".join(f"{l} {t}°C" for l, t in _get_temperatures())
    return (
        f"System hardware: {cpu} ({cores}, {freq}), {ram} RAM, "
        f"{gpu} ({vram} VRAM).  Storage: {disks}.  "
        f"Current thermals: {temps or 'unavailable'}."
    )


# ── Hardware collectors ───────────────────────────────────────────────────────

def _get_cpu_name() -> str:
    try:
        import wmi as _wmi
        procs = _wmi.WMI().Win32_Processor()
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


def _get_cpu_cores() -> str:
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
        logical  = psutil.cpu_count(logical=True)
        return f"{physical}C / {logical}T"
    except Exception:
        return "Unknown"


def _get_cpu_freq() -> str:
    try:
        import psutil
        freq = psutil.cpu_freq()
        if freq:
            cur  = freq.current / 1000
            base = freq.min / 1000 if freq.min else None
            maxi = freq.max / 1000 if freq.max else None
            parts = [f"{cur:.2f} GHz current"]
            if base:
                parts.append(f"{base:.2f} GHz base")
            if maxi:
                parts.append(f"{maxi:.2f} GHz max")
            return "  /  ".join(parts)
    except Exception:
        pass
    return "Unknown"


def _get_ram() -> str:
    try:
        import psutil
        vm = psutil.virtual_memory()
        total = vm.total / (1024 ** 3)
        used  = vm.used  / (1024 ** 3)
        pct   = vm.percent
        return f"{total:.1f} GB total  ({used:.1f} GB used  /  {pct:.0f}%)"
    except Exception:
        return "Unknown (psutil not available)"


def _get_gpu_name() -> str:
    # Strategy 1: GPUtil — works reliably on NVIDIA hardware
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            return "  |  ".join(g.name.strip() for g in gpus if g.name)
    except Exception:
        pass
    # Strategy 2: PowerShell Get-WmiObject (works even without the wmi package)
    try:
        import subprocess as _sp
        result = _sp.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Class Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=8,
            creationflags=_sp.CREATE_NO_WINDOW,
        )
        raw = result.stdout.strip()
        if raw and result.returncode == 0:
            return raw
    except Exception:
        pass
    # Strategy 3: wmi package
    try:
        import wmi as _wmi
        controllers = _wmi.WMI().Win32_VideoController()
        names = [g.Name.strip() for g in controllers if g.Name and g.Name.strip()]
        if names:
            return "  |  ".join(names)
    except Exception:
        pass
    return "Unknown GPU"


def _get_vram() -> str:
    # Strategy 1: GPUtil — most reliable on NVIDIA
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            return "  |  ".join(f"{g.memoryTotal / 1024:.1f} GB" for g in gpus)
    except Exception:
        pass
    # Strategy 2: PowerShell WMI
    try:
        import subprocess as _sp
        result = _sp.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Class Win32_VideoController).AdapterRAM"],
            capture_output=True, text=True, timeout=8,
            creationflags=_sp.CREATE_NO_WINDOW,
        )
        raw = result.stdout.strip()
        if raw and result.returncode == 0:
            mb = int(raw) // (1024 ** 2)
            if mb > 0:
                return f"{mb / 1024:.0f} GB"
    except Exception:
        pass
    # Strategy 3: wmi package
    try:
        import wmi as _wmi
        controllers = _wmi.WMI().Win32_VideoController()
        sizes = []
        for g in controllers:
            try:
                mb = int(g.AdapterRAM) // (1024 ** 2)
                if mb > 0:
                    sizes.append(f"{mb / 1024:.0f} GB")
            except Exception:
                pass
        if sizes:
            return "  |  ".join(sizes)
    except Exception:
        pass
    return "Unknown"


def _get_temperatures() -> list[tuple[str, float]]:
    """Return [(label, celsius), ...] from WMI or psutil sensors."""
    results: list[tuple[str, float]] = []
    try:
        import wmi as _wmi
        c = _wmi.WMI(namespace="root\\wmi")
        sensors = c.MSAcpi_ThermalZoneTemperature()
        for s in sensors:
            try:
                celsius = (s.CurrentTemperature / 10.0) - 273.15
                if 0 < celsius < 120:
                    name = getattr(s, "InstanceName", "Thermal Zone")
                    results.append((name[:20], round(celsius, 1)))
            except Exception:
                pass
    except Exception:
        pass

    if not results:
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            for chip, entries in temps.items():
                for e in entries:
                    if e.current and 0 < e.current < 120:
                        label = f"{chip}/{e.label}" if e.label else chip
                        results.append((label[:20], round(e.current, 1)))
        except Exception:
            pass

    return results[:8]  # cap output length


def _get_disk_usage() -> list[str]:
    """Return one line per physical drive with free/total in GB."""
    lines: list[str] = []
    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total = usage.total  / (1024 ** 3)
                free  = usage.free   / (1024 ** 3)
                used  = usage.used   / (1024 ** 3)
                pct   = usage.percent
                lines.append(
                    f"{part.device}  {total:.0f} GB total  "
                    f"{used:.0f} GB used  {free:.0f} GB free  ({pct:.0f}%)"
                )
            except Exception:
                pass
    except Exception:
        pass
    return lines or ["Disk info unavailable"]


def _get_top_processes(n: int = 5) -> list[str]:
    """Return the top N processes by RAM usage."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                mb = p.info["memory_info"].rss / (1024 ** 2)
                procs.append((mb, p.info["name"]))
            except Exception:
                pass
        procs.sort(reverse=True)
        return [f"{name:<30} {mb:>7.1f} MB" for mb, name in procs[:n]]
    except Exception:
        return ["Process info unavailable"]


# ── TEMP cleaner ──────────────────────────────────────────────────────────────

def _clear_temp() -> tuple[float, int]:
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
                try:
                    size = sum(
                        f.stat().st_size for f in entry.rglob("*") if f.is_file()
                    )
                except Exception:
                    size = 0
                shutil.rmtree(entry, ignore_errors=False)
                cleared_bytes += size
        except Exception:
            skipped += 1

    return cleared_bytes / (1024 * 1024), skipped
