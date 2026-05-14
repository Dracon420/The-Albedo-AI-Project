"""
albedo/vision.py  --  Webcam capture groundwork for moondream vision inference.

capture_vision() snaps a single frame from the webcam and returns it as an
RGB uint8 numpy array ready to pass directly to the moondream model.

Usage:
    from albedo.vision import capture_vision
    frame = capture_vision()          # default camera
    frame = capture_vision(device=1)  # second camera (e.g. USB webcam)
"""
from __future__ import annotations

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
