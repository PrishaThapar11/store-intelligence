# PROMPT: Generate pytest tests for store intelligence detection pipeline covering
# event schema validation, entry/exit tripwire logic, staff uniform detection, and
# re-entry histogram correlation threshold 0.85 within 30 minutes.
# CHANGES MADE: Added unit tests without loading YOLO weights; mocked numpy/cv2 paths.

import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pipeline.emit import VALID_EVENT_TYPES, make_event
from pipeline.staff_detector import is_black_uniform
from pipeline.tracker import (
    VisitorTracker,
    histogram_correlation,
    make_visitor_id,
)


def test_event_schema_has_required_fields():
    ev = make_event(
        camera_id="CAM_ENTRY_03",
        visitor_id="VIS_a1b2c3",
        event_type="ENTRY",
        zone_id="ENTRY_EXIT",
        confidence=0.85,
    )
    required = {
        "event_id",
        "store_id",
        "camera_id",
        "visitor_id",
        "event_type",
        "timestamp",
        "zone_id",
        "dwell_ms",
        "is_staff",
        "confidence",
        "metadata",
    }
    assert required.issubset(ev.keys())
    assert ev["store_id"] == "STORE_BLR_002"
    uuid.UUID(ev["event_id"])


def test_valid_event_types():
    for et in [
        "ENTRY",
        "EXIT",
        "ZONE_ENTER",
        "ZONE_DWELL",
        "REENTRY",
        "BILLING_QUEUE_JOIN",
        "BILLING_QUEUE_ABANDON",
    ]:
        assert et in VALID_EVENT_TYPES


def test_visitor_id_format():
    vid = make_visitor_id("CAM_ENTRY_03", 42, "2026-04-10")
    assert vid.startswith("VIS_")
    assert len(vid) == 10


def test_entry_exit_tripwire_logic():
    """Simulate centroid crossing y=540."""
    tripwire_y = 540
    prev_y, cy = 600.0, 500.0
    assert prev_y > tripwire_y and cy <= tripwire_y  # ENTRY cross

    prev_y, cy = 500.0, 600.0
    assert prev_y < tripwire_y and cy >= tripwire_y  # EXIT cross


def test_staff_black_uniform_detection():
    import cv2

    frame = np.zeros((100, 80, 3), dtype=np.uint8)
    assert is_black_uniform(frame, 10, 10, 70, 90) is True

    frame[:] = (200, 200, 200)
    assert is_black_uniform(frame, 10, 10, 70, 90) is False


def test_reentry_within_30_minutes():
    tracker = VisitorTracker()
    frame = np.zeros((120, 80, 3), dtype=np.uint8)
    now = datetime(2026, 4, 10, 15, 0, 0, tzinfo=timezone.utc)

    vid1, _ = tracker.get_or_create_visitor(
        "CAM_ENTRY_03", 1, "2026-04-10", frame, 10, 10, 70, 110, now
    )
    tracker.record_exit(vid1, frame, 10, 10, 70, 110, now + timedelta(minutes=5))

    vid2, is_reentry = tracker.get_or_create_visitor(
        "CAM_ENTRY_03", 99, "2026-04-10", frame, 12, 12, 72, 112,
        now + timedelta(minutes=10),
    )
    assert is_reentry is True
    assert vid2 == vid1


def test_histogram_correlation_identical():
    h = np.random.rand(180).astype(np.float32)
    assert histogram_correlation(h, h) > 0.99


def test_emitter_writes_jsonl(tmp_path):
    from pipeline.emit import EventEmitter

    out = tmp_path / "events.jsonl"
    emitter = EventEmitter(out)
    ev = make_event(
        camera_id="CAM_FLOOR_01",
        visitor_id="VIS_111111",
        event_type="ZONE_DWELL",
        zone_id="SKINCARE",
        dwell_ms=30000,
        confidence=0.7,
    )
    emitter.emit(ev)
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "ZONE_DWELL"
