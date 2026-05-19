"""
Unit tests for albedo.eel_app.bridge.

The bridge is a thin routing layer — tests verify that each exposed
function delegates to the right backend module and that errors are
caught and reported as ``{"ok": False, "error": ...}`` rather than
raising into the websocket.

Run:
    python tests/test_eel_bridge.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pre-import torch to avoid the GC race in resource_policy's first probe.
try:
    import torch                                                    # noqa: F401
except ImportError:
    pass

from albedo.eel_app import bridge                                   # noqa: E402


def _reset_swarm():
    """Reset the in-process swarm LED state between tests."""
    with bridge._swarm_lock:
        for k in bridge._swarm_state:
            bridge._swarm_state[k] = "standby"


# ---------------------------------------------------------------------------
# Lifecycle / diagnostics
# ---------------------------------------------------------------------------

def test_get_version_returns_app_metadata():
    r = bridge.get_version()
    assert r["ok"] is True
    assert "version" in r
    assert "uptime_s" in r
    assert r["ui"] == "eel"


def test_get_hardware_profile_routes_to_hardware_module():
    fake_hw = {"cpu": {"short": "Ryzen 5"}, "gpu": {"short": "RTX 2060"}}
    with patch("albedo.hardware_profile.get_hardware", return_value=fake_hw):
        r = bridge.get_hardware_profile()
    assert r["ok"] is True
    assert r["data"] == fake_hw


def test_get_resource_map_routes_to_resource_policy():
    fake_map = {"stt_whisper": {"device": "cpu", "demoted": "torch CPU-only build"}}
    with patch("albedo.resource_policy.detect", return_value=fake_map):
        r = bridge.get_resource_map()
    assert r["ok"] is True
    assert r["data"] == fake_map


def test_get_resource_map_returns_error_dict_on_failure():
    def boom():
        raise RuntimeError("simulated failure")
    with patch("albedo.resource_policy.detect", side_effect=boom):
        r = bridge.get_resource_map()
    assert r["ok"] is False
    assert "RuntimeError" in r["error"]


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def test_get_telemetry_routes_to_telemetry_module():
    fake_t = {"cpu": {"percent": 12.3}, "ram": {"percent": 50.0}}
    with patch("albedo.telemetry.get_full_telemetry", return_value=fake_t):
        r = bridge.get_telemetry()
    assert r["ok"] is True
    assert r["data"]["cpu"]["percent"] == 12.3


def test_get_telemetry_returns_error_dict_on_failure():
    with patch("albedo.telemetry.get_full_telemetry",
               side_effect=OSError("no sensors")):
        r = bridge.get_telemetry()
    assert r["ok"] is False
    assert "OSError" in r["error"]


# ---------------------------------------------------------------------------
# Swarm LEDs
# ---------------------------------------------------------------------------

def test_get_swarm_status_returns_three_agents():
    _reset_swarm()
    r = bridge.get_swarm_status()
    assert r["ok"] is True
    assert set(r["data"].keys()) == {
        "ALBEDO_CORE", "WEB_SCRAPER", "EXECUTION_OVERRIDE",
    }
    for state in r["data"].values():
        assert state in ("standby", "active", "error")


def test_set_swarm_state_updates_one_agent():
    _reset_swarm()
    bridge.set_swarm_state("ALBEDO_CORE", "active")
    r = bridge.get_swarm_status()
    assert r["data"]["ALBEDO_CORE"]       == "active"
    assert r["data"]["WEB_SCRAPER"]       == "standby"
    assert r["data"]["EXECUTION_OVERRIDE"] == "standby"


def test_set_swarm_state_ignores_unknown_agent():
    _reset_swarm()
    bridge.set_swarm_state("UNKNOWN_AGENT", "active")
    r = bridge.get_swarm_status()
    assert "UNKNOWN_AGENT" not in r["data"]


def test_set_swarm_state_clamps_unknown_states_to_standby():
    _reset_swarm()
    bridge.set_swarm_state("ALBEDO_CORE", "florp")
    r = bridge.get_swarm_status()
    assert r["data"]["ALBEDO_CORE"] == "standby"


# ---------------------------------------------------------------------------
# Comm mode + wake state — exercises Phase 4 N+3 hookup
# ---------------------------------------------------------------------------

def test_comm_mode_round_trip_persists():
    # Use a tempdir-isolated settings file via patch
    import tempfile
    from albedo.audio import comm_mode
    with tempfile.TemporaryDirectory() as td:
        with patch.object(comm_mode, "_SETTINGS_FILE",
                          Path(td) / "settings.json"):
            comm_mode._reset_for_tests()
            r1 = bridge.set_comm_mode("ptt")
            assert r1["ok"] is True
            assert r1["mode"] == "ptt"

            r2 = bridge.get_comm_mode()
            assert r2["ok"] is True
            assert r2["mode"] == "ptt"


def test_wake_state_round_trip_persists():
    import tempfile
    from albedo.audio import comm_mode
    with tempfile.TemporaryDirectory() as td:
        with patch.object(comm_mode, "_SETTINGS_FILE",
                          Path(td) / "settings.json"):
            comm_mode._reset_for_tests()
            r1 = bridge.set_wake_state("armed")
            assert r1["ok"] is True
            assert r1["state"] == "armed"

            r2 = bridge.get_wake_state()
            assert r2["ok"] is True
            assert r2["state"] == "armed"


# ---------------------------------------------------------------------------
# Chat — send_query routing
# ---------------------------------------------------------------------------

def test_send_query_routes_to_pipeline():
    _reset_swarm()
    with patch("albedo.pipeline.run", return_value="hello back"):
        r = bridge.send_query("hi there")
    assert r["ok"] is True
    assert r["reply"]   == "hello back"
    assert r["used_web"] is False


def test_send_query_web_prefix_forces_web_search():
    _reset_swarm()
    captured = {}
    def fake_run(text, use_web=False):
        captured["text"]    = text
        captured["use_web"] = use_web
        return "(web reply)"
    with patch("albedo.pipeline.run", side_effect=fake_run):
        r = bridge.send_query("web: who won?", use_web=False)
    assert r["ok"] is True
    assert r["used_web"] is True
    assert captured["use_web"] is True
    assert captured["text"]    == "who won?"


def test_send_query_empty_input_returns_error():
    r = bridge.send_query("   ")
    assert r["ok"] is False
    assert "empty" in r["error"].lower()


def test_send_query_pipeline_failure_returns_error_dict():
    _reset_swarm()
    with patch("albedo.pipeline.run", side_effect=RuntimeError("LLM down")):
        r = bridge.send_query("anything")
    assert r["ok"] is False
    assert "LLM down" in r["error"]
    # And the swarm LED should reflect the error
    assert bridge.get_swarm_status()["data"]["ALBEDO_CORE"] == "error"


# ---------------------------------------------------------------------------
# Webhook drain
# ---------------------------------------------------------------------------

def test_pop_webhook_updates_returns_drained_list():
    fake_updates = [{"kind": "speak", "payload": {"text": "x"}, "source": "mobile"}]
    with patch("albedo.webhook.pop_pending_updates", return_value=fake_updates):
        r = bridge.pop_webhook_updates()
    assert r["ok"] is True
    assert r["updates"] == fake_updates


# ---------------------------------------------------------------------------
# Neural links + app state
# ---------------------------------------------------------------------------

def test_get_neural_links_returns_all_required_subsystems():
    r = bridge.get_neural_links()
    assert r["ok"] is True
    for name in ("GEMINI", "GROQ", "TOGETHER", "OLLAMA",
                 "VEC_DB", "STT", "TTS", "WAKE", "WEBHOOK"):
        assert name in r["data"], f"missing neural link: {name}"
        entry = r["data"][name]
        assert "status" in entry and "label" in entry
        assert entry["status"] in ("ready", "active", "standby", "off", "error")


def test_neural_links_reflect_env_configuration():
    """GEMINI/GROQ/TOGETHER report 'ready' when their API key is set, 'off' otherwise."""
    saved = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY")}
    try:
        os.environ["GEMINI_API_KEY"]   = "fake-key"
        os.environ.pop("GROQ_API_KEY",     None)
        os.environ.pop("TOGETHER_API_KEY", None)
        r = bridge.get_neural_links()
        assert r["data"]["GEMINI"]["status"]   == "ready"
        assert r["data"]["GROQ"]["status"]     == "off"
        assert r["data"]["TOGETHER"]["status"] == "off"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_neural_links_stt_reflects_audio_stt_env_var():
    """AUDIO_STT=whisper reports WHISPER label; AUDIO_STT=vosk reports VOSK; etc."""
    saved = os.environ.get("AUDIO_STT")
    try:
        os.environ["AUDIO_STT"] = "whisper"
        r = bridge.get_neural_links()
        assert r["data"]["STT"]["label"] == "WHISPER"

        os.environ["AUDIO_STT"] = "vosk"
        r = bridge.get_neural_links()
        assert r["data"]["STT"]["label"] == "VOSK"
    finally:
        if saved is None: os.environ.pop("AUDIO_STT", None)
        else:             os.environ["AUDIO_STT"] = saved


def test_update_neural_link_overrides_static_state():
    """Backend code can push live state — must override the env-detected status."""
    saved = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"] = "fake-key"
        # Before override: ready (config-derived)
        assert bridge.get_neural_links()["data"]["GEMINI"]["status"] == "ready"
        # Push live override
        bridge.update_neural_link("GEMINI", "active")
        assert bridge.get_neural_links()["data"]["GEMINI"]["status"] == "active"
        # Clear with empty status
        bridge.update_neural_link("GEMINI", "")
        assert bridge.get_neural_links()["data"]["GEMINI"]["status"] == "ready"
    finally:
        if saved is None: os.environ.pop("GEMINI_API_KEY", None)
        else:             os.environ["GEMINI_API_KEY"] = saved
        bridge._live_states.clear()


def test_update_neural_link_clamps_invalid_status():
    bridge.update_neural_link("OLLAMA", "florp")   # not a valid state
    r = bridge.get_neural_links()
    # Should have been clamped to "standby" by update_neural_link
    assert r["data"]["OLLAMA"]["status"] == "standby"
    bridge._live_states.clear()


def test_get_app_state_reflects_swarm_aggregate():
    _reset_swarm()
    # All standby -> STANDBY
    r = bridge.get_app_state()
    assert r["state"] == "STANDBY"
    # Any active -> ACTIVE
    bridge.set_swarm_state("ALBEDO_CORE", "active")
    r = bridge.get_app_state()
    assert r["state"] == "ACTIVE"
    # Any error -> ERROR (takes priority over active)
    bridge.set_swarm_state("WEB_SCRAPER", "error")
    r = bridge.get_app_state()
    assert r["state"] == "ERROR"
    _reset_swarm()


# ---------------------------------------------------------------------------
# Settings — read + write
# ---------------------------------------------------------------------------

def test_get_settings_returns_settings_and_choices(tmp_path=None):
    """Drawer settings panel needs both the current values + the choice enums."""
    import tempfile, json
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b'{"active_persona": "jarvis", "vision_temperature": 0.42}')
        sf = Path(f.name)
    try:
        with patch.object(bridge, "_SETTINGS_FILE", sf):
            r = bridge.get_settings()
        assert r["ok"] is True
        assert r["settings"]["active_persona"]     == "jarvis"
        assert r["settings"]["vision_temperature"] == 0.42
        # Defaults must be filled for missing keys
        assert "audio_input_device"  in r["settings"]
        assert "audio_output_device" in r["settings"]
        # Choices include personas + auto-update + vision range
        assert "cortana" in r["choices"]["active_persona"]
        assert "jarvis"  in r["choices"]["active_persona"]
        assert isinstance(r["choices"]["auto_update"], list)
        assert r["choices"]["vision_temperature"]["min"] == 0.0
        assert r["choices"]["vision_temperature"]["max"] == 1.0
    finally:
        sf.unlink(missing_ok=True)


def test_get_settings_with_missing_file_returns_defaults():
    """A fresh install has no settings.json — should not error."""
    with patch.object(bridge, "_SETTINGS_FILE", Path("/does/not/exist.json")):
        r = bridge.get_settings()
    assert r["ok"] is True
    assert r["settings"]["active_persona"] == "cortana"


def test_set_setting_persists_to_disk():
    import tempfile, json
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b'{"existing_key": "existing_value"}')
        sf = Path(f.name)
    try:
        with patch.object(bridge, "_SETTINGS_FILE", sf):
            r = bridge.set_setting("active_persona", "jarvis")
            assert r["ok"] is True
            assert r["key"]   == "active_persona"
            assert r["value"] == "jarvis"
        # Verify on disk
        data = json.loads(sf.read_text(encoding="utf-8"))
        assert data["active_persona"] == "jarvis"
        # AND existing keys preserved
        assert data["existing_key"]   == "existing_value"
    finally:
        sf.unlink(missing_ok=True)


def test_set_setting_rejects_empty_key():
    r = bridge.set_setting("", "x")
    assert r["ok"] is False
    assert "missing key" in r["error"]


def test_get_audio_devices_returns_inputs_and_outputs():
    """Stub sounddevice so the test doesn't depend on real audio hardware."""
    import types
    fake_sd = types.SimpleNamespace(
        query_devices=lambda: [
            {"name": "Mic A", "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Spk B", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Both",  "max_input_channels": 2, "max_output_channels": 2},
        ],
        default=types.SimpleNamespace(device=(0, 1)),
    )
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        r = bridge.get_audio_devices()
    assert r["ok"] is True
    assert len(r["inputs"])  == 2   # Mic A + Both
    assert len(r["outputs"]) == 2   # Spk B + Both
    assert r["inputs"][0]["default"] is True   # index 0 = Mic A
    assert r["outputs"][0]["default"] is True  # index 1 = Spk B


def test_get_audio_devices_handles_missing_sounddevice():
    """No sounddevice installed → error dict, not exception."""
    with patch.dict(sys.modules, {"sounddevice": None}):
        # Need to force re-import attempt inside the function
        with patch.object(bridge, "get_audio_devices", side_effect=lambda: bridge.get_audio_devices.__wrapped__()) if hasattr(bridge.get_audio_devices, "__wrapped__") else patch.object(bridge, "_settings_lock", bridge._settings_lock):
            pass
    # Simpler: just assert that calling with a broken import returns an error dict
    import builtins
    real_import = builtins.__import__
    def fail_sd(name, *a, **kw):
        if name == "sounddevice":
            raise ImportError("no sounddevice")
        return real_import(name, *a, **kw)
    with patch("builtins.__import__", side_effect=fail_sd):
        r = bridge.get_audio_devices()
    assert r["ok"] is False
    assert "ImportError" in r["error"] or "sounddevice" in r["error"]


# ---------------------------------------------------------------------------
# Background list
# ---------------------------------------------------------------------------

def test_get_backgrounds_returns_four_files():
    r = bridge.get_backgrounds()
    assert r["ok"] is True
    assert len(r["files"]) == 4
    for f in r["files"]:
        assert f.lower().endswith(".png")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import faulthandler, inspect, os, traceback
    faulthandler.enable()
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
    os._exit(0 if failed == 0 else 1)
