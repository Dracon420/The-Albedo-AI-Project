"""
Unit tests for albedo.resource_policy — focuses on the CUDA-availability
reconciliation logic and the policy-table contract. Probes are mocked
so tests run identically on a CPU-only build, a CUDA dev box, and CI.

Run:
    python tests/test_resource_policy.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from albedo import resource_policy                                  # noqa: E402


def _reset():
    resource_policy.reset()


# ---------------------------------------------------------------------------
# Probes — mocked CUDA on / CUDA off scenarios
# ---------------------------------------------------------------------------

def test_cuda_unavailable_when_torch_says_no():
    """If torch.cuda.is_available() is False, CUDA is rejected even with nvidia-smi."""
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=False), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=True):
        assert resource_policy.cuda_available() is False


def test_cuda_unavailable_when_no_nvidia_smi():
    """Conversely, nvidia-smi missing also rejects CUDA."""
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=True), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=False):
        assert resource_policy.cuda_available() is False


def test_cuda_available_only_when_both_succeed():
    """Both probes True → CUDA available."""
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=True), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=True):
        assert resource_policy.cuda_available() is True


# ---------------------------------------------------------------------------
# Policy reconciliation — fallback chain
# ---------------------------------------------------------------------------

def test_whisper_falls_back_to_cpu_without_cuda():
    """Phase 6 fix #1 — distil-whisper must NOT hard-crash on non-NVIDIA hosts."""
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=False), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=False):
        assert resource_policy.device_for("stt_whisper") == "cpu"
        entry = resource_policy.detect()["stt_whisper"]
        assert entry["demoted"] is not None
        assert "torch" in entry["demoted"] or "nvidia-smi" in entry["demoted"]


def test_whisper_uses_cuda_when_available():
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=True), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=True):
        assert resource_policy.device_for("stt_whisper") == "cuda"
        assert resource_policy.detect()["stt_whisper"]["demoted"] is None


def test_cpu_only_components_unaffected_by_cuda_state():
    """Kokoro / OpenWakeWord are CPU-only by policy — must not change with CUDA."""
    for cuda_state in (True, False):
        _reset()
        with patch.object(resource_policy, "_probe_torch_cuda", return_value=cuda_state), \
             patch.object(resource_policy, "_probe_nvidia_smi", return_value=cuda_state):
            assert resource_policy.device_for("tts_kokoro") == "cpu"
            assert resource_policy.device_for("wakeword")   == "cpu"


# ---------------------------------------------------------------------------
# Eager / lazy load contract
# ---------------------------------------------------------------------------

def test_whisper_is_lazy():
    """Phase 6 fix #2 — distil-whisper does NOT load at boot; only on Deepgram fail."""
    _reset()
    assert resource_policy.should_load_eagerly("stt_whisper") is False


def test_eager_components_load_at_boot():
    _reset()
    for comp in ("tts_kokoro", "wakeword", "stt_deepgram", "eel_server", "telemetry"):
        assert resource_policy.should_load_eagerly(comp) is True, \
            f"{comp} should be eager"


# ---------------------------------------------------------------------------
# ONNX providers list
# ---------------------------------------------------------------------------

def test_providers_for_onnx_cpu_component():
    _reset()
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=False), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=False):
        assert resource_policy.providers_for("tts_kokoro") == ["CPUExecutionProvider"]


def test_providers_for_non_onnx_returns_empty():
    _reset()
    assert resource_policy.providers_for("stt_whisper") == []
    assert resource_policy.providers_for("telemetry")   == []


def test_providers_includes_cuda_only_when_onnx_cuda_present():
    """Even if torch sees CUDA, ONNX needs onnxruntime-gpu to use CUDAExecutionProvider."""
    _reset()
    # If we ever flip a component's preferred to "cuda" + runtime=onnx, this proves the gate works.
    with patch.object(resource_policy, "_probe_torch_cuda", return_value=True), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=True), \
         patch.object(resource_policy, "_probe_onnx_providers",
                      return_value=["CPUExecutionProvider"]):
        # tts_kokoro is CPU-only by policy, so it stays CPU regardless.
        assert resource_policy.providers_for("tts_kokoro") == ["CPUExecutionProvider"]


# ---------------------------------------------------------------------------
# Schema robustness
# ---------------------------------------------------------------------------

def test_unknown_component_raises_keyerror():
    _reset()
    raised = False
    try:
        resource_policy.device_for("not_a_component_typo")
    except KeyError as exc:
        raised = True
        assert "not_a_component_typo" in str(exc)
        assert "Known:" in str(exc), "error must hint at the valid list"
    assert raised


def test_detect_is_cached():
    """detect() must not re-spawn nvidia-smi on every call."""
    _reset()
    call_count = {"n": 0}

    def counting_probe():
        call_count["n"] += 1
        return False

    with patch.object(resource_policy, "_probe_torch_cuda", side_effect=counting_probe), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=False):
        resource_policy.detect()
        resource_policy.detect()
        resource_policy.detect()
    # _probe_torch_cuda called once per detect() that wasn't cached.
    # First detect() builds; next two should hit cache.
    assert call_count["n"] <= 1, f"detect() must cache, but probe ran {call_count['n']} times"


def test_force_refresh_rebuilds():
    _reset()
    resource_policy.detect()
    call_count = {"n": 0}

    def counting_probe():
        call_count["n"] += 1
        return False

    with patch.object(resource_policy, "_probe_torch_cuda", side_effect=counting_probe), \
         patch.object(resource_policy, "_probe_nvidia_smi", return_value=False):
        resource_policy.detect(force=True)
    assert call_count["n"] >= 1


# ---------------------------------------------------------------------------
# Persistence — log_resource_map merges into hardware_config.json
# ---------------------------------------------------------------------------

def test_log_resource_map_merges_into_hardware_config(tmp_path=None):
    """The crash recorder picks up the active resource map via hardware_config.json."""
    _reset()
    from albedo import hardware_profile
    hw_path = hardware_profile.cache_path()
    # Ensure the file exists
    if not hw_path.exists():
        hardware_profile.get_hardware()

    resource_policy.log_resource_map()

    data = json.loads(hw_path.read_text(encoding="utf-8"))
    assert "resource_map" in data, "resource_map key must be present in hardware_config.json"
    for needed in ("tts_kokoro", "stt_whisper", "wakeword", "telemetry"):
        assert needed in data["resource_map"], f"missing key: {needed}"
        assert "device" in data["resource_map"][needed]


def test_log_resource_map_writes_human_log():
    _reset()
    resource_policy.log_resource_map()
    p = resource_policy.map_path()
    assert p.exists()
    body = p.read_text(encoding="utf-8")
    assert "Albedo resource map" in body
    assert "tts_kokoro" in body
    assert "stt_whisper" in body


# ---------------------------------------------------------------------------
# Standalone runner
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
