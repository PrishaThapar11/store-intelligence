"""Seed synthetic visitor events when DB is empty (docker acceptance on clean machine)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta  # noqa: F401 — used in _generate_synthetic
from pathlib import Path

from app.database import get_session_factory
from app.models import EventRow, SessionRow, STORE_ID

logger = logging.getLogger(__name__)
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_events.jsonl"


def bootstrap_if_empty() -> None:
    factory = get_session_factory()
    db = factory()
    try:
        count = db.query(EventRow).count()
        if count > 0:
            return

        if SAMPLE_PATH.exists():
            _load_jsonl(db, SAMPLE_PATH)
            logger.info("Bootstrapped events from sample_events.jsonl")
            return

        _generate_synthetic(db)
        logger.info("Bootstrapped synthetic demo events")
    finally:
        db.close()


def _load_jsonl(db, path: Path) -> None:
    from app.ingestion import parse_ts
    from app.database import metadata_to_json

    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    if not events:
        return
    first_ts = parse_ts(events[0]["timestamp"])
    offset = datetime.utcnow() - first_ts

    for ev in events:
        ts = parse_ts(ev["timestamp"]) + offset
        db.add(
                EventRow(
                    event_id=ev["event_id"],
                    store_id=ev["store_id"],
                    camera_id=ev["camera_id"],
                    visitor_id=ev["visitor_id"],
                    event_type=ev["event_type"],
                    timestamp=ts,
                    zone_id=ev.get("zone_id"),
                    dwell_ms=ev.get("dwell_ms", 0),
                    is_staff=ev.get("is_staff", False),
                    confidence=ev.get("confidence", 0.0),
                    metadata_json=metadata_to_json(ev.get("metadata", {})),
                    queue_depth=(ev.get("metadata") or {}).get("queue_depth"),
                )
            )
    db.commit()


def _generate_synthetic(db) -> None:
    base = datetime.utcnow() - timedelta(hours=2)
    visitors = [f"VIS_{h:06x}"[:10] for h in range(0xA1B2C1, 0xA1B2C1 + 8)]
    seq = 0
    for i, vid in enumerate(visitors):
        is_staff = i == 7
        ts_entry = base + timedelta(minutes=i * 3)
        events = [
            ("ENTRY", "ENTRY_EXIT", 0),
            ("ZONE_ENTER", "SKINCARE", 0),
            ("ZONE_DWELL", "SKINCARE", 30000),
            ("ZONE_ENTER", "MAKEUP", 0),
            ("BILLING_QUEUE_JOIN", "BILLING", 0),
        ]
        if i < 3:
            events.append(("EXIT", "ENTRY_EXIT", 0))
        for etype, zone, dwell in events:
            seq += 1
            ts = ts_entry + timedelta(seconds=seq * 15)
            meta = {"queue_depth": 2 if etype == "BILLING_QUEUE_JOIN" else None, "session_seq": seq}
            db.add(
                EventRow(
                    event_id=str(uuid.uuid4()),
                    store_id=STORE_ID,
                    camera_id="CAM_ENTRY_03" if zone == "ENTRY_EXIT" else "CAM_FLOOR_01",
                    visitor_id=vid,
                    event_type=etype,
                    timestamp=ts,
                    zone_id=zone,
                    dwell_ms=dwell,
                    is_staff=is_staff,
                    confidence=0.88,
                    metadata_json=json.dumps(meta),
                    queue_depth=meta.get("queue_depth"),
                )
            )
        if not is_staff:
            db.add(
                SessionRow(
                    session_id=str(uuid.uuid4()),
                    visitor_id=vid,
                    store_id=STORE_ID,
                    entry_time=ts_entry,
                    exit_time=ts_entry + timedelta(minutes=20) if i < 3 else None,
                    converted=i < 2,
                    zones_visited="SKINCARE,MAKEUP",
                    is_staff=False,
                    near_billing=i < 5,
                )
            )
    db.commit()
