"""Staff classification by uniform color and camera zone."""
from __future__ import annotations

import numpy as np


def torso_region(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    """Upper 50% of bounding box as torso proxy."""
    h = max(1, y2 - y1)
    torso_y2 = y1 + int(h * 0.5)
    return frame[max(0, y1) : torso_y2, max(0, x1) : max(0, x2)]


def is_black_uniform(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> bool:
    """
    Staff wear black uniforms: Hue any, Saturation < 50, Value < 80.
    Flag if >60% of torso pixels match.
    """
    import cv2

    region = torso_region(frame, x1, y1, x2, y2)
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    mask = (s < 50) & (v < 80)
    ratio = float(np.sum(mask)) / max(1, mask.size)
    return ratio > 0.60


def classify_staff(
    camera_id: str,
    frame: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    force_staff_cameras: frozenset[str] | None = None,
) -> bool:
    """CAM_BACK_04 (stockroom) is always staff."""
    force = force_staff_cameras or frozenset({"CAM_BACK_04"})
    if camera_id in force:
        return True
    if camera_id in ("CAM_FLOOR_01", "CAM_FLOOR_02"):
        return is_black_uniform(frame, x1, y1, x2, y2)
    return False
