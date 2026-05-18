"""
safety_catch.py — interceptor for swarm-initiated subprocess execution.

Wraps subprocess.run so that any command the LLM swarm tries to execute is
first routed through an approval handler. The handler decides interactively
whether to allow the command (returning the subprocess result) or deny it
(raising CommandDenied). Every request and decision is appended to
``logs/safety_audit.log`` for forensic review.

The approval handler is **pluggable** — this matters because the UI layer
changes (Tk now, Eel later, headless server soon), and each context needs
its own way to ask the user. Defaults are conservative: a console y/n
prompt when an interactive stdin is available, automatic denial otherwise.
Code at startup should call ``set_approval_handler()`` with whatever fits
the current environment (Tk messagebox, Eel JS callback, webhook approval
queue, etc.).

An **allowlist** of pre-approved command patterns skips the prompt entirely
for read-only telemetry calls (nvidia-smi, taskkill of our own pythonw,
etc.) so the UI isn't constantly asking permission for housekeeping.

Public API
----------
    safe_run(argv, *, requester="user", **subprocess_kwargs) -> CompletedProcess
        Drop-in replacement for subprocess.run(). Approval is required
        for commands not on the allowlist. Raises CommandDenied on refusal.

    add_allowed(pattern: str) -> None
        Add a regex pattern that auto-approves matching commands (joined argv).

    set_approval_handler(handler: Callable[[PendingApproval], bool]) -> None
        Replace the default handler. The handler is called from whatever
        thread invoked safe_run — it must be safe to block there.

    PendingApproval (dataclass)
        Snapshot of one approval request — id, argv, cwd, requester, ts.

    CommandDenied (Exception)
        Raised when the handler returns False (or times out / errors).

    pending_count() -> int
        Number of approval requests currently in flight (for UI badges).

    audit_log_path() -> Path
        Absolute path to the audit log.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Union

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT       = Path(__file__).resolve().parent.parent
_LOG_DIR    = _ROOT / "logs"
_AUDIT_FILE = _LOG_DIR / "safety_audit.log"


# ---------------------------------------------------------------------------
# Allowlist — patterns that auto-approve. Commands are joined to a single
# string with shlex.join() and tested against each regex with re.search.
# Keep this list intentionally short and read-only — anything that mutates
# system state should require approval.
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED: list[str] = [
    # GPU telemetry — read-only nvidia-smi queries
    r"^nvidia-smi --query-gpu=[^\s]+ --format=csv",

    # CPU/system telemetry — PowerShell read-only WMI
    r"^powershell .*Get-WmiObject -Class Win32_(Processor|OperatingSystem|ComputerSystem)",

    # taskkill ONLY for our own pythonw.exe (used by uninstaller)
    r"^taskkill /F /IM pythonw\.exe$",

    # platform.processor() fallback path
    r"^wmic cpu get Name /format:list$",
]

_allowed: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in _DEFAULT_ALLOWED]
_allow_lock = threading.Lock()


def add_allowed(pattern: str) -> None:
    """Compile and append a regex pattern to the allowlist."""
    with _allow_lock:
        _allowed.append(re.compile(pattern, re.IGNORECASE))


def _is_allowed(argv: list[str]) -> bool:
    """Return True if the joined argv matches any allowlist regex."""
    joined = shlex.join(argv) if hasattr(shlex, "join") else " ".join(
        shlex.quote(a) for a in argv)
    with _allow_lock:
        return any(p.search(joined) for p in _allowed)


# ---------------------------------------------------------------------------
# Request dataclass + custom exception
# ---------------------------------------------------------------------------

@dataclass
class PendingApproval:
    """One in-flight approval request handed to the registered handler."""
    id:        str
    argv:      list[str]
    cwd:       Optional[str]
    requester: str
    ts:        float
    # Best-effort display string — what the user sees in the prompt
    display:   str = field(default="")

    def as_dict(self) -> dict:
        return {
            "id":        self.id,
            "argv":      list(self.argv),
            "cwd":       self.cwd,
            "requester": self.requester,
            "ts":        self.ts,
            "display":   self.display,
        }


class CommandDenied(Exception):
    """Raised by safe_run() when the approval handler refuses a command."""

    def __init__(self, request: PendingApproval, reason: str = "denied"):
        self.request = request
        self.reason  = reason
        super().__init__(f"command denied ({reason}): {request.display}")


# ---------------------------------------------------------------------------
# Approval handler registry
# ---------------------------------------------------------------------------

ApprovalHandler = Callable[[PendingApproval], bool]
_handler: ApprovalHandler  # set below
_handler_lock = threading.Lock()


def _default_console_handler(req: PendingApproval) -> bool:
    """
    Console fallback handler. Used when no UI handler is registered.

    Prompts on stdin/stderr when interactive; otherwise auto-denies, so a
    headless or daemonized swarm never silently executes arbitrary commands.
    """
    if not (sys.stdin and sys.stdin.isatty()):
        # No interactive tty — fail closed.
        print(
            f"[safety_catch] AUTO-DENIED (no tty): {req.display}",
            file=sys.stderr,
        )
        return False
    try:
        sys.stderr.write(
            "\n[safety_catch] approval required\n"
            f"  requester : {req.requester}\n"
            f"  command   : {req.display}\n"
            f"  cwd       : {req.cwd or '<inherit>'}\n"
            "  approve?  [y/N] "
        )
        sys.stderr.flush()
        reply = sys.stdin.readline().strip().lower()
        return reply == "y" or reply == "yes"
    except Exception:
        return False


_handler = _default_console_handler


def set_approval_handler(handler: ApprovalHandler) -> None:
    """Replace the active approval handler. None resets to the console fallback."""
    global _handler
    with _handler_lock:
        _handler = handler if handler is not None else _default_console_handler


# ---------------------------------------------------------------------------
# In-flight tracking + audit log
# ---------------------------------------------------------------------------

_in_flight: dict[str, PendingApproval] = {}
_in_flight_lock = threading.Lock()


def pending_count() -> int:
    """How many approval requests are currently awaiting a handler decision."""
    with _in_flight_lock:
        return len(_in_flight)


def _audit(line: str) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts}  {line}\n")
    except Exception:
        # Audit failures must never crash the caller.
        pass


def audit_log_path() -> Path:
    return _AUDIT_FILE


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def safe_run(
    argv: Union[list[str], str],
    *,
    requester: str = "user",
    cwd: Optional[Union[str, os.PathLike]] = None,
    **subprocess_kwargs,
) -> subprocess.CompletedProcess:
    """
    Drop-in replacement for subprocess.run() with mandatory approval.

    On the allowlist  → executes immediately, audited as "ALLOWED (allowlist)".
    Off the allowlist → registered handler is consulted; on approval the
                         command runs and is audited as "APPROVED"; on
                         refusal the call raises CommandDenied and is
                         audited as "DENIED".

    Parameters
    ----------
    argv : list[str] or str
        Command and arguments. A string is split with shlex.split for
        consistent quoting; pass a list when you want full control.
    requester : str
        Source of the command — "swarm", "webhook", "user", etc. Recorded
        in the audit log so misbehaving callers can be traced.
    cwd : str | PathLike, optional
        Forwarded to subprocess.run. Also displayed to the user.
    **subprocess_kwargs
        Anything else subprocess.run accepts. ``shell=True`` is honored but
        strongly discouraged for swarm-routed calls.

    Raises
    ------
    CommandDenied
        Handler returned False (or raised).
    """
    if isinstance(argv, str):
        argv_list = shlex.split(argv, posix=(os.name != "nt"))
    else:
        argv_list = list(argv)

    if not argv_list:
        raise ValueError("safe_run requires a non-empty argv")

    display = shlex.join(argv_list) if hasattr(shlex, "join") else " ".join(
        shlex.quote(a) for a in argv_list)

    # Fast path: allowlist
    if _is_allowed(argv_list):
        _audit(f"ALLOWED (allowlist)  by={requester}  cmd={display}")
        return subprocess.run(argv_list, cwd=cwd, **subprocess_kwargs)

    # Slow path: human approval required
    req = PendingApproval(
        id=uuid.uuid4().hex[:12],
        argv=argv_list,
        cwd=str(cwd) if cwd is not None else None,
        requester=requester,
        ts=datetime.now().timestamp(),
        display=display,
    )

    with _in_flight_lock:
        _in_flight[req.id] = req

    try:
        with _handler_lock:
            handler = _handler
        try:
            approved = bool(handler(req))
        except Exception as exc:
            _audit(f"DENIED (handler error)  by={requester}  id={req.id}  cmd={display}  err={exc!r}")
            raise CommandDenied(req, reason=f"handler raised: {exc!r}") from exc
    finally:
        with _in_flight_lock:
            _in_flight.pop(req.id, None)

    if not approved:
        _audit(f"DENIED  by={requester}  id={req.id}  cmd={display}")
        raise CommandDenied(req)

    _audit(f"APPROVED  by={requester}  id={req.id}  cmd={display}")
    return subprocess.run(argv_list, cwd=cwd, **subprocess_kwargs)
