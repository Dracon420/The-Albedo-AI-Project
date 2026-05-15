"""
albedo/vision.py  --  Webcam capture and moondream visual analysis.

capture_vision() snaps one webcam frame and returns it as an RGB numpy array.
vision_query()   encodes that frame entirely in memory (no temp files) and
                 sends it to the Ollama moondream endpoint.

JPEG encoding uses cv2.imencode() → bytes buffer → base64.  _PROJECT_ROOT is
never referenced here; no file system paths are needed.

Usage:
    from albedo.vision import capture_vision, vision_query
    frame  = capture_vision()
    result = vision_query(frame, "What do you see?")

Requires: opencv-python, httpx, ollama pull moondream
"""
from __future__ import annotations

import base64
import traceback

import numpy as np


def capture_vision(device: int = 0) -> np.ndarray | None:
    """
    Capture one frame from the webcam.

    Returns HxWx3 uint8 RGB array, or None if capture fails.
    """
    try:
        import cv2
    except ImportError:
        print("[vision] opencv-python is not installed. Run: pip install opencv-python")
        return None

    cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"[vision] Could not open camera device {device}.")
        return None

    try:
        ret, frame = cap.read()
    finally:
        cap.release()

    if not ret or frame is None:
        print("[vision] Failed to read a frame from the camera.")
        return None

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def vision_query(
    frame: np.ndarray,
    prompt: str = "Describe in detail everything you see in this image.",
) -> str:
    """
    Send an RGB frame to Ollama moondream for visual analysis.

    Two-phase structure:
      Phase 1 -- resolve imports and encode the frame in memory.
                 Any failure here is a Python/environment problem and the
                 real traceback is surfaced, NOT a moondream warning.
      Phase 2 -- POST to Ollama.  Only here do we show Ollama-specific hints.
    """

    # ── Phase 1: imports + in-memory JPEG encode ───────────────────────────
    try:
        import cv2
        import httpx
        from albedo.config import OLLAMA_BASE_URL
    except Exception as exc:
        return (
            f"[vision] Setup error -- {type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc().strip()}"
        )

    try:
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return "[vision] cv2.imencode failed to compress the frame."
        img_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception as exc:
        return (
            f"[vision] Frame encode error -- {type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc().strip()}"
        )

    # ── Phase 2: Ollama request ────────────────────────────────────────────
    payload = {
        "model": "moondream",
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [img_b64],
            }
        ],
        "stream": False,
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    except httpx.ConnectError:
        return (
            "[vision] Cannot reach Ollama. Start it with:  ollama serve\n"
            "Then pull moondream if not already done:  ollama pull moondream"
        )
    except httpx.HTTPStatusError as exc:
        return (
            f"[vision] Ollama returned HTTP {exc.response.status_code}.\n"
            "Is moondream pulled?  Run:  ollama pull moondream"
        )
    except Exception as exc:
        return (
            f"[vision] Request error -- {type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc().strip()}"
        )
