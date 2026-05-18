"""
resource_policy.py — hardware assignment protocol for Albedo's ML stack.

Every model has a preferred execution device and a fallback chain. This
module is the single source of truth for "which model runs on what" so
the audio loaders in Phase 4 can never accidentally put two heavy models
on the same GPU and OOM the LLM.

Two-dimensional CUDA availability check
---------------------------------------
``torch.cuda.is_available()`` returns False on CPU-only torch builds even
when the machine has an RTX card. Conversely, nvidia-smi may report a GPU
on a system whose Python install lacks a CUDA-capable torch. So this
module probes BOTH and only considers CUDA available when:

  1. ``torch.cuda.is_available()`` returns True, AND
  2. ``nvidia-smi`` returns at least one GPU.

Any "want CUDA" entry that can't satisfy both gets demoted to its
fallback (typically CPU) and a one-line warning is logged.

Lazy load contract
------------------
Components marked ``eager=False`` are NOT loaded at boot. They get loaded
on first use only — typically when a primary stack fails over. distil-
whisper is the canonical example: it sits in VRAM only when Deepgram has
already failed, leaving the LLM the full GPU budget under normal use.

Phase 4 model loaders use this module:

    from albedo.resource_policy import providers_for, device_for

    # ONNX components (Kokoro, OpenWakeWord, etc.)
    tts = KokoroONNX(model_path, providers=providers_for("tts_kokoro"))

    # Torch/transformers components (distil-whisper)
    def load_whisper():
        return WhisperModel("distil-small.en",
                            device=device_for("stt_whisper"))

Public API
----------
    detect() -> dict                # one-shot probe, builds the effective map
    device_for(component) -> str    # "cuda" | "cpu"
    providers_for(component) -> list[str]   # ONNX providers list
    should_load_eagerly(component) -> bool
    vram_budget_mb(component) -> int        # advisory only
    log_resource_map() -> None      # writes the active map to logs/
    map_path() -> Path
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

_ROOT     = Path(__file__).resolve().parent.parent
_LOG_DIR  = _ROOT / "logs"
_MAP_FILE = _LOG_DIR / "resource_map.log"

# Hidden-window flag — Windows only, no-op elsewhere.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW   # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0


# ---------------------------------------------------------------------------
# Policy table — declarative, edit-here-only.
#
# Each entry describes what the component WANTS. detect() reconciles the
# wishlist against what the host can actually provide and produces the
# EFFECTIVE map. The "eager" flag controls whether boot should pre-load
# the component (True) or wait for first use (False — VRAM hygiene).
# vram_budget_mb is advisory only; nothing enforces it yet, but the value
# guides Phase 4 sizing decisions.
# ---------------------------------------------------------------------------

_POLICY: dict[str, dict] = {
    "wakeword": {
        "runtime":       "onnx",
        "preferred":     "cpu",
        "fallback":      None,
        "eager":         True,
        "vram_budget":   0,
        "description":   "OpenWakeWord persistent listener",
    },
    "tts_kokoro": {
        "runtime":       "onnx",
        "preferred":     "cpu",
        "fallback":      None,
        "eager":         True,
        "vram_budget":   0,
        "description":   "Kokoro TTS ONNX runtime",
    },
    "stt_whisper": {
        "runtime":       "torch",
        "preferred":     "cuda",
        "fallback":      "cpu",
        "eager":         False,                # LAZY — only on Deepgram fail
        "vram_budget":   1200,                 # distil-small.en ~1.2 GB on cuda
        "description":   "distil-whisper offline STT fallback",
    },
    "stt_deepgram": {
        "runtime":       "network",            # cloud websocket — no local device
        "preferred":     "network",
        "fallback":      None,
        "eager":         True,
        "vram_budget":   0,
        "description":   "Deepgram cloud STT WebSocket",
    },
    "eel_server": {
        "runtime":       "python",
        "preferred":     "cpu",
        "fallback":      None,
        "eager":         True,
        "vram_budget":   0,
        "description":   "Eel desktop window asyncio loop",
    },
    "telemetry": {
        "runtime":       "python",
        "preferred":     "cpu",
        "fallback":      None,
        "eager":         True,
        "vram_budget":   0,
        "description":   "Live host telemetry delta calculator",
    },
}


# ---------------------------------------------------------------------------
# Probes — never raise, return what they can determine
# ---------------------------------------------------------------------------

def _probe_torch_cuda() -> bool:
    """True if installed torch can dispatch to CUDA."""
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _probe_nvidia_smi() -> bool:
    """True if nvidia-smi reports at least one GPU. Independent of torch."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
            creationflags=_NO_WINDOW,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _probe_onnx_providers() -> list[str]:
    """Return the providers list onnxruntime can actually use on this host."""
    try:
        import onnxruntime
        return list(onnxruntime.get_available_providers())
    except Exception:
        return []


def cuda_available() -> bool:
    """
    Effective CUDA availability — both torch knows it AND nvidia-smi sees
    a GPU. Either alone is insufficient: CPU-only torch builds happily run
    on a machine with an RTX card, and nvidia-smi can outlive its driver
    after a reboot loop.
    """
    return _probe_torch_cuda() and _probe_nvidia_smi()


def onnx_cuda_available() -> bool:
    """True if onnxruntime has a CUDA provider available."""
    return "CUDAExecutionProvider" in _probe_onnx_providers()


# ---------------------------------------------------------------------------
# Effective map — what the components ACTUALLY get
# ---------------------------------------------------------------------------

_effective: Optional[dict[str, dict]] = None


def _resolve_device(want: str, fallback: Optional[str]) -> tuple[str, Optional[str]]:
    """
    Reconcile a 'want CUDA' against host reality. Returns (granted, reason_demoted).

    reason_demoted is None on a successful grant, else a short human-readable
    reason like 'torch CPU-only build; no nvidia-smi GPU'.
    """
    if want != "cuda":
        return want, None

    # Probe each dimension exactly once, then both decide and explain.
    torch_ok  = _probe_torch_cuda()
    nvsmi_ok  = _probe_nvidia_smi()
    if torch_ok and nvsmi_ok:
        return "cuda", None

    # Demote to fallback (or CPU if no explicit fallback given).
    granted = fallback or "cpu"
    if granted == "cuda":
        granted = "cpu"
    reasons: list[str] = []
    if not torch_ok:
        reasons.append("torch CPU-only build")
    if not nvsmi_ok:
        reasons.append("no nvidia-smi GPU")
    return granted, "; ".join(reasons) or "CUDA unavailable"


def _providers_for_resolved(runtime: str, device: str) -> list[str]:
    """Map (runtime, device) → ONNX providers list. CPU is universal."""
    if runtime != "onnx":
        return []
    if device == "cuda" and onnx_cuda_available():
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def detect(force: bool = False) -> dict[str, dict]:
    """
    Probe the host, build the effective resource map, cache it.

    Cached so repeat callers don't re-spawn nvidia-smi. Pass force=True
    after a driver reload or environment change.
    """
    global _effective
    if _effective is not None and not force:
        return _effective

    result: dict[str, dict] = {}
    for name, spec in _POLICY.items():
        granted, demoted_reason = _resolve_device(spec["preferred"], spec["fallback"])
        entry = {
            "runtime":       spec["runtime"],
            "preferred":     spec["preferred"],
            "device":        granted,
            "providers":     _providers_for_resolved(spec["runtime"], granted),
            "eager":         spec["eager"],
            "vram_budget":   spec["vram_budget"],
            "description":   spec["description"],
            "demoted":       demoted_reason,        # None on clean grant
        }
        result[name] = entry
    _effective = result
    return result


def reset() -> None:
    """Drop the cached map. Tests use this; production code doesn't need to."""
    global _effective
    _effective = None


# ---------------------------------------------------------------------------
# Public accessors — what Phase 4 model loaders import
# ---------------------------------------------------------------------------

def _entry(component: str) -> dict:
    m = detect()
    if component not in m:
        raise KeyError(
            f"unknown resource policy component {component!r}. "
            f"Known: {sorted(m.keys())}"
        )
    return m[component]


def device_for(component: str) -> str:
    """'cuda' or 'cpu' (or 'network' for cloud components)."""
    return _entry(component)["device"]


def providers_for(component: str) -> list[str]:
    """ONNX providers list. Returns [] for non-ONNX components."""
    return list(_entry(component)["providers"])


def should_load_eagerly(component: str) -> bool:
    return bool(_entry(component)["eager"])


def vram_budget_mb(component: str) -> int:
    return int(_entry(component)["vram_budget"])


# ---------------------------------------------------------------------------
# Logging + persistence
# ---------------------------------------------------------------------------

def log_resource_map() -> None:
    """
    Write the active resource map to logs/resource_map.log AND merge it
    into hardware_config.json under a ``resource_map`` key so crash
    reports include it automatically.
    """
    m = detect()
    # 1. Plain-text log (human-readable)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        lines = [f"# Albedo resource map  {ts}", ""]
        for name, e in m.items():
            tag = e["device"]
            if e["demoted"]:
                tag += f" (demoted: {e['demoted']})"
            eager = "eager" if e["eager"] else "lazy"
            lines.append(
                f"  {name:14}  {e['runtime']:8}  {tag:36}  {eager}  -- {e['description']}"
            )
        lines.append("")
        with open(_MAP_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass

    # 2. Merge into hardware_config.json so crash recorder sees it
    try:
        from albedo.hardware_profile import cache_path
        hw_file = cache_path()
        data: dict = {}
        if hw_file.exists():
            try:
                data = json.loads(hw_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        # Strip noisy fields for the embedded copy
        data["resource_map"] = {
            name: {k: v for k, v in entry.items() if k != "description"}
            for name, entry in m.items()
        }
        hw_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def map_path() -> Path:
    return _MAP_FILE
