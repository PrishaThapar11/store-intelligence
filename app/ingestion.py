"""POST /events/ingest with deduplication and session updates."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, metadata_to_json
from app.models import EventRow, IngestRequest, IngestResponse, SessionRow, STORE_ID

logger = logging.getLogger(__name__)
router = APIRouter()


def parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).replace(tzinfo=None)


@router.post("/events/ingest", response_model=IngestResponse)
def ingest_events(body: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    if len(body.events) > 500:
        raise HTTPException(status_code=400, detail="Batch limit is 500 events")

    accepted = 0
    duplicates = 0
    rejected = 0
    errors: list[dict] = []

    for ev in body.events:
        try:
            if ev.store_id != STORE_ID:
                rejected += 1
                errors.append({"event_id": ev.event_id, "error": "invalid store_id"})
                continue

            existing = db.query(EventRow).filter(EventRow.event_id == ev.event_id).first()
            if existing:
                duplicates += 1
                continue

            ts = parse_ts(ev.timestamp)
            meta = ev.metadata.model_dump() if hasattr(ev.metadata, "model_dump") else dict(ev.metadata)
            row = EventRow(
                event_id=ev.event_id,
                store_id=ev.store_id,
                camera_id=ev.camera_id,
                visitor_id=ev.visitor_id,
                event_type=ev.event_type,
                timestamp=ts,
                zone_id=ev.zone_id,
                dwell_ms=ev.dwell_ms,
                is_staff=ev.is_staff,
                confidence=ev.confidence,
                metadata_json=metadata_to_json(meta),
                queue_depth=meta.get("queue_depth"),
            )
            db.add(row)
            _update_session(db, ev, ts)
            accepted += 1
        except Exception as e:
            rejected += 1
            errors.append({"event_id": getattr(ev, "event_id", None), "error": str(e)})

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Ingest commit failed: %s", e)
        raise HTTPException(status_code=503, detail="Database commit failed") from e

    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
    )


def _update_session(db: Session, ev, ts: datetime) -> None:
    if ev.is_staff:
        return

    session = (
        db.query(SessionRow)
        .filter(
            SessionRow.visitor_id == ev.visitor_id,
            SessionRow.store_id == ev.store_id,
            SessionRow.exit_time.is_(None),
        )
        .order_by(SessionRow.entry_time.desc())
        .first()
    )

    if ev.event_type in ("ENTRY", "REENTRY"):
        if ev.event_type == "REENTRY" and session:
            return
        if not session:
            db.add(
                SessionRow(
                    session_id=str(uuid.uuid4()),
                    visitor_id=ev.visitor_id,
                    store_id=ev.store_id,
                    entry_time=ts,
                    is_staff=False,
                    zones_visited="",
                )
            )
    elif ev.event_type == "EXIT" and session:
        session.exit_time = ts
        if session.entry_time:
            pass
    elif ev.event_type == "ZONE_ENTER" and session and ev.zone_id:
        zones = [z for z in (session.zones_visited or "").split(",") if z]
        if ev.zone_id not in zones:
            zones.append(ev.zone_id)
            session.zones_visited = ",".join(zones)
    elif ev.event_type == "BILLING_QUEUE_JOIN" and session:
        session.near_billing = True
