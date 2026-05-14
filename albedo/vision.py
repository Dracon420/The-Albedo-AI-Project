"""
albedo/vision.py  --  Webcam capture and moondream visual analysis.

capture_vision() snaps one webcam frame and returns it as an RGB numpy array.
vision_query()   sends that frame to Ollama moondream and returns the analysis.

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
                Use 1 for a secondary USB camera.

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

    Args:
        frame:  HxWx3 uint8 RGB array from capture_vision().
        prompt: Natural-language instruction for moondream.

    Returns:
        Model response string. Returns an error message instead of raising
        so callers can display it directly in the chat log.

    Prerequisite: ollama pull moondream
    """
    try:
        import cv2
        import httpx
        from albedo.config import OLLAMA_BASE_URL

        # Encode RGB frame as JPEG bytes then base64
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
    except Exception as exc:
        return (
            f"[vision] Error: {exc}\n"
            "Is moondream pulled? Run: ollama pull moondream"
        )
