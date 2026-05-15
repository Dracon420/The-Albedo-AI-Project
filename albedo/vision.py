"""
albedo/vision.py  --  Webcam capture and moondream visual analysis.

capture_vision() snaps one webcam frame and returns it as an RGB numpy array.
vision_query()   encodes that frame entirely in memory and sends it to the
                 Ollama moondream endpoint, returning the analysis string.

No temporary files are written to disk -- the JPEG is held in a bytes buffer
and base64-encoded in memory before being POSTed to Ollama.

Usage:
    from albedo.vision import capture_vision, vision_query
    frame  = capture_vision()
    result = vision_query(frame, "What do you see?")

Requires: opencv-python, httpx, ollama pull moondream
"""
from __future__ import annotations

import base64
import numpy as np


def capture_vision(device: int = 0) -> np.ndarray | None:
    """
    Capture one frame from the webcam.

    Args:
        device: OpenCV camera index. 0 = first camera (usually the webcam).

    Returns:
        HxWx3 uint8 numpy array in RGB order, or None if capture fails.
    """
    try:
        import cv2
    except ImportError:
        print("[vision] opencv-python is not installed. "
              "Run: pip install opencv-python")
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

    # OpenCV returns BGR; moondream and PIL expect RGB.
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def vision_query(
    frame: np.ndarray,
    prompt: str = "Describe in detail everything you see in this image.",
) -> str:
    """
    Send an RGB frame to Ollama moondream for visual analysis.

    The frame is JPEG-encoded entirely in memory (no temp files) and
    base64-encoded before being POSTed to the Ollama chat endpoint.

    Args:
        frame:  HxWx3 uint8 RGB array from capture_vision().
        prompt: Natural-language instruction for moondream.

    Returns:
        Model response string. Returns a plain error message on failure so
        callers can display it directly without catching exceptions.

    Prerequisite: ollama pull moondream
    """
    try:
        import cv2
        import httpx
        from albedo.config import OLLAMA_BASE_URL

        # Encode RGB frame → JPEG bytes → base64, entirely in memory
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return "[vision] JPEG encode failed."
        img_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

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
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    except httpx.ConnectError:
        return "[vision] Ollama is not running. Start it with: ollama serve"
    except httpx.HTTPStatusError as exc:
        return f"[vision] Ollama returned HTTP {exc.response.status_code}. Is moondream pulled? Run: ollama pull moondream"
    except Exception as exc:
        return f"[vision] Unexpected error: {type(exc).__name__}: {exc}"
