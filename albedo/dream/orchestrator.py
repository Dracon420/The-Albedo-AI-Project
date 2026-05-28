"""
dream/orchestrator.py — Dream cycle state machine.

Coordinates the three phases of Albedo's autonomous idle processing:
    Phase 1 — File organization   (file_organizer.organize)
    Phase 2 — System cataloging   (cataloger.build_catalog)
    Phase 3 — Memory consolidation (operative_dream.initiate_rem_cycle)

Called by idle_monitor when the inactivity threshold is reached.
Immediately pauses if the user returns (interrupt flag checked between
every major operation).

State machine
-------------
    IDLE  →  (idle threshold)  →  DREAMING
    DREAMING  →  (user returns)  →  INTERRUPTED
    DREAMING  →  (all phases done)  →  COOLDOWN
    INTERRUPTED / COOLDOWN  →  IDLE  (after cooldown expires)

Public API
----------
    start_dream(status_cb=None)   Called by idle_monitor on idle detection
    interrupt_dream()             Called by idle_monitor on user return
    get_state() -> str            "IDLE" | "DREAMING" | "INTERRUPTED" | "COOLDOWN"
    get_last_report() -> dict     Summary of the most recent completed dream
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_STATE_IDLE        = "IDLE"
_STATE_DREAMING    = "DREAMING"
_STATE_INTERRUPTED = "INTERRUPTED"
_STATE_COOLDOWN    = "COOLDOWN"

_state:       str                         = _STATE_IDLE
_state_lock:  threading.Lock             = threading.Lock()
_interrupt:   threading.Event            = threading.Event()
_last_report: dict                       = {}
_status_cb:   Optional[Callable[[str, str], None]] = None  # (state, detail)


def get_state() -> str:
    with _state_lock:
        return _state


def get_last_report() -> dict:
    return dict(_last_report)


def _set_state(new_state: str, detail: str = "") -> None:
    global _state
    with _state_lock:
        _state = new_state
    print(f"[dream] State → {new_state}  {detail}")
    if _status_cb:
        try:
            _status_cb(new_state, detail)
        except Exception:
            pass


def _is_interrupted() -> bool:
    return _interrupt.is_set()


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def _run_phase1(report: dict) -> None:
    """File organization."""
    _set_state(_STATE_DREAMING, "Phase 1 — File Organization")
    try:
        from albedo.dream.file_organizer import organize

        def _prog(msg: str, frac: float) -> None:
            if _status_cb:
                _status_cb(_STATE_DREAMING, f"[1/3] {msg}")

        moves = organize(interrupt=_is_interrupted, progress_cb=_prog)
        report["phase1_moves"] = len(moves)
        report["phase1_manifest"] = [m.as_dict() for m in moves]
        print(f"[dream] Phase 1 complete — {len(moves)} files organized.")
    except Exception as exc:
        print(f"[dream] Phase 1 error: {exc}")
        report["phase1_error"] = str(exc)
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[1/3] Error: {exc}")


def _run_phase2(report: dict, forced: bool = False) -> None:
    """System cataloging."""
    # Only skip on interrupt if NOT a forced manual run.
    # Clicking Force Dream Now registers as user activity → sets _interrupt;
    # forced=True bypasses that so phases 2/3 always run when manually triggered.
    if not forced and _is_interrupted():
        print("[dream] Phase 2 skipped — interrupted.")
        return
    _set_state(_STATE_DREAMING, "Phase 2 — System Catalog")
    try:
        from albedo.dream.cataloger import build_catalog

        def _prog(msg: str, frac: float) -> None:
            if _status_cb:
                _status_cb(_STATE_DREAMING, f"[2/3] {msg}")

        # Pass the interrupt only for long inner loops, not at phase boundary
        interruptor = None if forced else _is_interrupted
        result = build_catalog(interrupt=interruptor, progress_cb=_prog)
        report["phase2_files"]    = result.total_files
        report["phase2_indexed"]  = result.indexed
        report["phase2_size_mb"]  = result.total_size_mb
        report["phase2_by_cat"]   = result.by_category
        report["phase2_vault"]    = result.vault_note
        print(f"[dream] Phase 2 complete — {result.total_files} files cataloged, "
              f"{result.indexed} indexed.")
        if _status_cb:
            _status_cb(_STATE_DREAMING,
                       f"[2/3] Complete — {result.total_files:,} files, "
                       f"{result.indexed:,} indexed.")
    except Exception as exc:
        print(f"[dream] Phase 2 error: {exc}")
        report["phase2_error"] = str(exc)
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[2/3] Error: {exc}")


def _run_phase4_brain(report: dict, forced: bool = False) -> None:
    """Brain growth — Smart Brain auto-linking, mining, synthesis."""
    if not forced and _is_interrupted():
        print("[dream] Phase 4 skipped — interrupted.")
        return
    _set_state(_STATE_DREAMING, "Phase 4 — Brain Growth")
    try:
        from albedo.dream.brain_growth import run_growth_cycle

        if _status_cb:
            _status_cb(_STATE_DREAMING, "[4/4] Brain growth — reindexing vault…")

        # Alternate depth: every 4th dream is a deep cycle (synthesis + MOC)
        import time as _t
        deep_marker = Path(__file__).parent / ".deep_cycle_counter"
        count = 0
        if deep_marker.exists():
            try:
                count = int(deep_marker.read_text()) + 1
            except Exception:
                count = 0
        deep_marker.write_text(str(count))

        depth = "deep" if count % 4 == 0 else "medium"
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[4/4] Brain growth ({depth} cycle)…")

        result = run_growth_cycle(depth=depth)
        report["phase4_brain"] = result
        print(f"[dream] Phase 4 complete — {result}")
        if _status_cb:
            mined = result.get("mined_notes", 0)
            linked = result.get("autolinked", 0)
            synth  = result.get("synthesised", 0)
            _status_cb(_STATE_DREAMING,
                       f"[4/4] Brain: {mined} mined, {linked} linked, {synth} synthesised")
    except Exception as exc:
        print(f"[dream] Phase 4 error: {exc}")
        report["phase4_error"] = str(exc)
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[4/4] Error: {exc}")


def _run_phase3(report: dict, forced: bool = False) -> None:
    """Memory consolidation (REM cycle)."""
    if not forced and _is_interrupted():
        print("[dream] Phase 3 skipped — interrupted.")
        return
    _set_state(_STATE_DREAMING, "Phase 3 — Memory Consolidation")
    try:
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        import importlib
        od = importlib.import_module("operative_dream")

        if _status_cb:
            _status_cb(_STATE_DREAMING, "[3/3] Consolidating memory traces…")

        status = od.initiate_rem_cycle()
        report["phase3_status"] = str(status) if status else "complete"
        print(f"[dream] Phase 3 complete — {report['phase3_status']}")
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[3/3] {report['phase3_status']}")
    except RuntimeError as exc:
        # Common case: OBSIDIAN_VAULT_PATH not set — non-fatal, note it and move on
        msg = f"[3/3] Skipped — {exc}"
        print(f"[dream] Phase 3 skipped: {exc}")
        report["phase3_skipped"] = str(exc)
        if _status_cb:
            _status_cb(_STATE_DREAMING, msg)
    except Exception as exc:
        print(f"[dream] Phase 3 error: {exc}")
        report["phase3_error"] = str(exc)
        if _status_cb:
            _status_cb(_STATE_DREAMING, f"[3/3] Error: {exc}")


# ---------------------------------------------------------------------------
# Main dream cycle
# ---------------------------------------------------------------------------

def start_dream(status_cb: Optional[Callable[[str, str], None]] = None,
                forced: bool = False) -> None:
    """
    Entry point called by idle_monitor (forced=False) or Force Dream Now button
    (forced=True).

    forced=True skips inter-phase interrupt checks so that clicking the manual
    trigger — which generates a mouse-activity event that would otherwise set
    the interrupt flag — doesn't cause phases 2 and 3 to bail immediately.
    """
    global _status_cb, _last_report

    with _state_lock:
        if _state == _STATE_DREAMING:
            print("[dream] Dream already active — skipping duplicate trigger.")
            return

    _interrupt.clear()
    _status_cb = status_cb
    _set_state(_STATE_DREAMING, "Initiating dream cycle…")

    report: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "interrupted": False,
        "forced":      forced,
    }

    try:
        _run_phase1(report)
        _run_phase2(report, forced=forced)
        _run_phase3(report, forced=forced)
        _run_phase4_brain(report, forced=forced)
    except Exception as exc:
        print(f"[dream] Unhandled error in dream cycle: {exc}")
        report["fatal_error"] = str(exc)
    finally:
        report["ended_at"]    = datetime.now().isoformat(timespec="seconds")
        report["interrupted"] = _is_interrupted()
        _last_report          = report

        if _is_interrupted():
            _set_state(_STATE_INTERRUPTED,
                       f"Interrupted after {report.get('phase1_moves', 0)} moves.")
        else:
            _set_state(_STATE_COOLDOWN, "Dream complete. Entering cooldown.")

        # Transition back to IDLE after a short display delay
        def _back_to_idle() -> None:
            time.sleep(30)
            _set_state(_STATE_IDLE, "Watching for next idle window.")

        threading.Thread(target=_back_to_idle, daemon=True).start()


def interrupt_dream() -> None:
    """Signal the dream cycle to stop at the next checkpoint."""
    if get_state() == _STATE_DREAMING:
        print("[dream] Interrupt requested — will stop at next checkpoint.")
        _interrupt.set()
