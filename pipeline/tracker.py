"""Visitor ID assignment and Re-ID using HSV histogram correlation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from scipy.stats import pearsonr


def make_visitor_id(camera_id: str, track_id: int, date_str: str) -> str:
    raw = f"{camera_id}{track_id}{date_str}"
    digest = hashlib.md5(raw.encode()).hexdigest()[:6]
    return f"VIS_{digest}"


def appearance_histogram(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    import cv2

    crop = frame[max(0, y1) : y2, max(0, x1) : x2]
    if crop.size == 0:
        return np.zeros(180, dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], None, [180], [0, 180])
    cv2.normalize(hist, hist)
    return hist.flatten().astype(np.float32)


def histogram_correlation(h1: np.ndarray, h2: np.ndarray) -> float:
    if h1.size == 0 or h2.size == 0:
        return 0.0
    try:
        corr, _ = pearsonr(h1, h2)
        return float(corr) if not np.isnan(corr) else 0.0
    except Exception:
        return 0.0


@dataclass
class ExitRecord:
    visitor_id: str
    exit_time: datetime
    histogram: np.ndarray


@dataclass
class VisitorTracker:
    """Track exits and detect re-entry within 30 minutes."""

    reentry_window_minutes: int = 30
    correlation_threshold: float = 0.85
    _exits: list[ExitRecord] = field(default_factory=list)
    _track_to_visitor: dict[tuple[str, int], str] = field(default_factory=dict)

    def get_or_create_visitor(
        self,
        camera_id: str,
        track_id: int,
        date_str: str,
        frame: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        now: datetime,
    ) -> tuple[str, bool]:
        """
        Returns (visitor_id, is_reentry).
        Re-entry if appearance matches prior exit within window.
        """
        key = (camera_id, track_id)
        if key in self._track_to_visitor:
            return self._track_to_visitor[key], False

        hist = appearance_histogram(frame, x1, y1, x2, y2)
        cutoff = now - timedelta(minutes=self.reentry_window_minutes)
        for rec in reversed(self._exits):
            if rec.exit_time < cutoff:
                continue
            if histogram_correlation(hist, rec.histogram) >= self.correlation_threshold:
                self._track_to_visitor[key] = rec.visitor_id
                return rec.visitor_id, True

        vid = make_visitor_id(camera_id, track_id, date_str)
        self._track_to_visitor[key] = vid
        return vid, False

    def record_exit(
        self,
        visitor_id: str,
        frame: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        exit_time: datetime,
    ) -> None:
        hist = appearance_histogram(frame, x1, y1, x2, y2)
        self._exits.append(ExitRecord(visitor_id, exit_time, hist))
        # Prune old exits
        cutoff = exit_time - timedelta(minutes=self.reentry_window_minutes)
        self._exits = [e for e in self._exits if e.exit_time >= cutoff]
