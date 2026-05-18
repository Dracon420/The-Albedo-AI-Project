"""
black_box.py — global crash recorder for Albedo.

Installs hooks that catch every unhandled exception (main thread + worker
threads) and dump a structured crash report to ``logs/albedo_crash_report.txt``
before the process exits. The report includes the timestamp, exception
metadata, full traceback, app version, Python version, OS info, and a
snapshot of loaded modules to help reproduce hard-to-trigger crashes.

Designed to be the very first thing main.py calls — even before importing
heavy dependencies — so a crash in any import chain still produces a report.

Public API:
    install()           -- idempotent; call once at process start
    write_report(exc)   -- manually log a caught exception (does not exit)
    crash_log_path()    -- absolute path to the crash log
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — resolved relative to this file, not the CWD, so launcher matters
# never matter.
# ---------------------------------------------------------------------------
_ROOT     = Path(__file__).resolve().parent.parent
_LOG_DIR  = _ROOT / "logs"
_LOG_FILE = _LOG_DIR / "albedo_crash_report.txt"

# Idempotency guard — install() is safe to call repeatedly
_INSTALLED = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _app_version() -> str:
    vf = _ROOT / "VERSION"
    try:
        return vf.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _system_snapshot() -> str:
    """One-line system summary — kept short so reports stay readable."""
    import platform
    try:
        return (
            f"{platform.system()} {platform.release()} ({platform.version()}) | "
            f"Python {sys.version.split()[0]} | "
            f"PID {os.getpid()} | "
            f"Albedo v{_app_version()}"
        )
    except Exception:
        return f"PID {os.getpid()} | Albedo v{_app_version()}"


def _format_report(
    where: str,
    exc_type: type,
    exc_value: BaseException,
    exc_tb,
    thread_name: str | None = None,
) -> str:
    parts: list[str] = []
    parts.append("=" * 78)
    parts.append(f"ALBEDO CRASH REPORT  {datetime.now():%Y-%m-%d %H:%M:%S}")
    parts.append("=" * 78)
    parts.append(f"Source        : {where}")
    if thread_name:
        parts.append(f"Thread        : {thread_name}")
    parts.append(f"Exception     : {exc_type.__name__}: {exc_value}")
    parts.append(f"System        : {_system_snapshot()}")
    parts.append("")
    parts.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    return "\n".join(parts) + "\n"


def _write(report: str) -> None:
    """Append to the crash log. Never raises — best-effort only."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(report)
    except Exception:
        # Last-resort: emit to stderr so something is visible in a console.
        try:
            sys.stderr.write(report)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------

def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """Replacement for sys.excepthook — runs on main-thread unhandled errors."""
    # Don't trap Ctrl-C — it's expected user behavior.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    report = _format_report("sys.excepthook (main thread)",
                            exc_type, exc_value, exc_tb)
    _write(report)
    # Also call the original hook so the user sees the trace in their console.
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


def _threading_excepthook(args) -> None:
    """Replacement for threading.excepthook (Python 3.8+) — catches thread crashes."""
    # SystemExit raised inside a thread is suppressed by default — keep that behaviour.
    if issubclass(args.exc_type, SystemExit):
        return
    report = _format_report(
        "threading.excepthook (worker thread)",
        args.exc_type, args.exc_value, args.exc_traceback,
        thread_name=getattr(args.thread, "name", None),
    )
    _write(report)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install() -> None:
    """Install both crash hooks. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):  # Python 3.8+
        threading.excepthook = _threading_excepthook
    _INSTALLED = True


def write_report(exc: BaseException, where: str = "manual") -> None:
    """Log a caught exception without altering control flow."""
    report = _format_report(
        where, type(exc), exc, exc.__traceback__,
        thread_name=threading.current_thread().name,
    )
    _write(report)


def crash_log_path() -> Path:
    """Absolute path to the crash log file (may not exist yet)."""
    return _LOG_FILE
