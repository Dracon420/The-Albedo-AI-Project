"""
Unit tests for albedo.audio.comm_mode.

Each test redirects the settings file to a tempdir so the real
settings.json next to the install root isn't disturbed.

Run:
    python tests/test_comm_mode.py
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from albedo.audio import comm_mode                                  # noqa: E402
from albedo.audio.comm_mode import CommMode, WakeState              # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolate_settings(tmp_path: Path):
    """Point comm_mode at a per-test settings.json. Returns a patch context manager."""
    return patch.object(comm_mode, "_SETTINGS_FILE", tmp_path / "settings.json")


def _reset_state():
    comm_mode._reset_for_tests()


# ---------------------------------------------------------------------------
# Defaults — preserve v2.0.2 behaviour
# ---------------------------------------------------------------------------

def test_defaults_are_latch_and_disarmed(tmp_path):
    """Fresh install (no settings.json) defaults to LATCH + DISARMED."""
    _reset_state()
    with _isolate_settings(tmp_path):
        assert comm_mode.get_mode()       == CommMode.LATCH
        assert comm_mode.get_wake_state() == WakeState.DISARMED


def test_defaults_when_settings_file_is_corrupt(tmp_path):
    """A malformed settings.json must not break the module."""
    _reset_state()
    settings = tmp_path / "settings.json"
    settings.write_text("{ not valid json ", encoding="utf-8")
    with _isolate_settings(tmp_path):
        assert comm_mode.get_mode()       == CommMode.LATCH
        assert comm_mode.get_wake_state() == WakeState.DISARMED


def test_unknown_string_values_fall_back_to_default(tmp_path):
    """settings.json that says comm_mode='garbage' must not crash."""
    _reset_state()
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "comm_mode": "wat", "wake_state": "also wat",
    }), encoding="utf-8")
    with _isolate_settings(tmp_path):
        assert comm_mode.get_mode()       == CommMode.LATCH
        assert comm_mode.get_wake_state() == WakeState.DISARMED


# ---------------------------------------------------------------------------
# Setter semantics
# ---------------------------------------------------------------------------

def test_set_mode_persists_to_disk(tmp_path):
    _reset_state()
    settings_path = tmp_path / "settings.json"
    with _isolate_settings(tmp_path):
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
        assert comm_mode.get_mode() == CommMode.PUSH_TO_TALK
        body = json.loads(settings_path.read_text(encoding="utf-8"))
        assert body["comm_mode"] == "ptt"


def test_set_wake_state_persists_to_disk(tmp_path):
    _reset_state()
    settings_path = tmp_path / "settings.json"
    with _isolate_settings(tmp_path):
        comm_mode.set_wake_state(WakeState.ARMED)
        assert comm_mode.get_wake_state() == WakeState.ARMED
        body = json.loads(settings_path.read_text(encoding="utf-8"))
        assert body["wake_state"] == "armed"


def test_set_preserves_other_settings_keys(tmp_path):
    """Writing comm_mode state must not wipe gui.py's persistence keys."""
    _reset_state()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "audio_input_device": 11, "active_persona": "cortana",
        "background": "Albedo 2",
    }), encoding="utf-8")
    with _isolate_settings(tmp_path):
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
        comm_mode.set_wake_state(WakeState.ARMED)
        body = json.loads(settings_path.read_text(encoding="utf-8"))
    assert body["audio_input_device"] == 11
    assert body["active_persona"]     == "cortana"
    assert body["background"]         == "Albedo 2"
    assert body["comm_mode"]          == "ptt"
    assert body["wake_state"]         == "armed"


def test_state_survives_module_reload(tmp_path):
    """After set+reload(), getter returns the persisted value, not the default."""
    _reset_state()
    with _isolate_settings(tmp_path):
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
        comm_mode.set_wake_state(WakeState.ARMED)
        comm_mode.reload()
        assert comm_mode.get_mode()       == CommMode.PUSH_TO_TALK
        assert comm_mode.get_wake_state() == WakeState.ARMED


def test_string_input_is_coerced_to_enum(tmp_path):
    """set_mode('ptt') and set_mode(CommMode.PUSH_TO_TALK) must behave the same."""
    _reset_state()
    with _isolate_settings(tmp_path):
        comm_mode.set_mode("ptt")          # type: ignore[arg-type]
        assert comm_mode.get_mode() == CommMode.PUSH_TO_TALK
        comm_mode.set_wake_state("armed")  # type: ignore[arg-type]
        assert comm_mode.get_wake_state() == WakeState.ARMED


# ---------------------------------------------------------------------------
# Observers
# ---------------------------------------------------------------------------

def test_mode_observer_fires_on_change(tmp_path):
    _reset_state()
    seen: list = []
    with _isolate_settings(tmp_path):
        comm_mode.on_mode_change(lambda m: seen.append(m))
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
    assert seen == [CommMode.PUSH_TO_TALK]


def test_observer_does_not_fire_on_idempotent_set(tmp_path):
    """Setting LATCH when already in LATCH must not re-notify observers."""
    _reset_state()
    seen: list = []
    with _isolate_settings(tmp_path):
        comm_mode.on_mode_change(lambda m: seen.append(m))
        # Mode is LATCH by default
        comm_mode.set_mode(CommMode.LATCH)
    assert seen == []


def test_wake_observer_fires_on_change(tmp_path):
    _reset_state()
    seen: list = []
    with _isolate_settings(tmp_path):
        comm_mode.on_wake_change(lambda s: seen.append(s))
        comm_mode.set_wake_state(WakeState.ARMED)
        comm_mode.set_wake_state(WakeState.DISARMED)
    assert seen == [WakeState.ARMED, WakeState.DISARMED]


def test_buggy_observer_does_not_break_setter(tmp_path):
    """A handler that raises must not prevent the state change from persisting."""
    _reset_state()
    def bad(_):
        raise RuntimeError("UI crashed")
    with _isolate_settings(tmp_path):
        comm_mode.on_mode_change(bad)
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
        # Setter must still have applied the state
        assert comm_mode.get_mode() == CommMode.PUSH_TO_TALK


def test_clear_observers_drops_all_subscriptions(tmp_path):
    _reset_state()
    seen: list = []
    with _isolate_settings(tmp_path):
        comm_mode.on_mode_change(lambda m: seen.append(m))
        comm_mode.on_wake_change(lambda s: seen.append(s))
        comm_mode.clear_observers()
        comm_mode.set_mode(CommMode.PUSH_TO_TALK)
        comm_mode.set_wake_state(WakeState.ARMED)
    assert seen == []


# ---------------------------------------------------------------------------
# Thread safety — no torn state under concurrent writers
# ---------------------------------------------------------------------------

def test_concurrent_writers_settle_to_a_consistent_state(tmp_path):
    """No assertion on which value wins, only that the result is one of the
    valid enum values (not a torn write)."""
    _reset_state()
    with _isolate_settings(tmp_path):
        def writer(n_iters, m):
            for _ in range(n_iters):
                comm_mode.set_mode(m)
        threads = [
            threading.Thread(target=writer, args=(100, CommMode.PUSH_TO_TALK)),
            threading.Thread(target=writer, args=(100, CommMode.LATCH)),
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        final = comm_mode.get_mode()
    assert final in (CommMode.PUSH_TO_TALK, CommMode.LATCH)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, os, tempfile, shutil, traceback
    faulthandler.enable()
    mod = sys.modules[__name__]
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        sig = inspect.signature(fn)
        td = None
        try:
            if "tmp_path" in sig.parameters:
                td = tempfile.mkdtemp(prefix=f"comm_test_{name}_")
                fn(Path(td))
            else:
                fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
        finally:
            if td:
                shutil.rmtree(td, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    os._exit(0 if failed == 0 else 1)
