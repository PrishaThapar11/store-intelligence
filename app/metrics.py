"""GET /stores/{store_id}/metrics computation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EventRow, MetricsResponse, POSTransactionRow, SessionRow, STORE_ID

router = APIRouter()


def _mark_conversions(db: Session, store_id: str) -> None:
    """Mark sessions converted if visitor was in BILLING within 5 min of a POS txn."""
    sessions = (
        db.query(SessionRow)
        .filter(SessionRow.store_id == store_id, SessionRow.is_staff == False)  # noqa: E712
        .all()
    )
    txns = db.query(POSTransactionRow).filter(POSTransactionRow.store_id == store_id).all()

    for sess in sessions:
        if sess.converted:
            continue
        billing_events = (
            db.query(EventRow)
            .filter(
                EventRow.visitor_id == sess.visitor_id,
                EventRow.store_id == store_id,
                EventRow.zone_id == "BILLING",
                EventRow.is_staff == False,  # noqa: E712
            )
            .all()
        )
        for txn in txns:
            for be in billing_events:
                delta = abs((txn.timestamp - be.timestamp).total_seconds())
                if delta <= 300:
                    sess.converted = True
                    break
            if sess.converted:
                break


@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
def get_metrics(store_id: str, db: Session = Depends(get_db)) -> MetricsResponse:
    if store_id != STORE_ID:
        store_id = STORE_ID

    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    _mark_conversions(db, store_id)
    db.commit()

    unique_visitors = (
        db.query(func.count(func.distinct(EventRow.visitor_id)))
        .filter(
            EventRow.store_id == store_id,
            EventRow.is_staff == False,  # noqa: E712
            EventRow.timestamp >= since,
        )
        .scalar()
        or 0
    )

    total_sessions = (
        db.query(func.count(SessionRow.session_id))
        .filter(SessionRow.store_id == store_id, SessionRow.is_staff == False)  # noqa: E712
        .scalar()
        or 0
    )
    converted_sessions = (
        db.query(func.count(SessionRow.session_id))
        .filter(
            SessionRow.store_id == store_id,
            SessionRow.is_staff == False,  # noqa: E712
            SessionRow.converted == True,  # noqa: E712
        )
        .scalar()
        or 0
    )
    conversion_rate = (
        float(converted_sessions) / float(total_sessions) if total_sessions > 0 else 0.0
    )

    dwell_rows = (
        db.query(EventRow.zone_id, func.avg(EventRow.dwell_ms))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "ZONE_DWELL",
            EventRow.is_staff == False,  # noqa: E712
            EventRow.zone_id.isnot(None),
        )
        .group_by(EventRow.zone_id)
        .all()
    )
    avg_dwell_per_zone = {z: float(avg or 0) for z, avg in dwell_rows}

    latest_billing = (
        db.query(EventRow)
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type.in_(["BILLING_QUEUE_JOIN", "ZONE_ENTER"]),
            EventRow.zone_id == "BILLING",
        )
        .order_by(EventRow.timestamp.desc())
        .limit(50)
        .all()
    )
    queue_depth = 0
    for ev in latest_billing:
        try:
            meta = json.loads(ev.metadata_json or "{}")
            if meta.get("queue_depth") is not None:
                queue_depth = int(meta["queue_depth"])
                break
        except json.JSONDecodeError:
            pass
    if queue_depth == 0:
        queue_depth = (
            db.query(func.count(func.distinct(EventRow.visitor_id)))
            .filter(
                EventRow.store_id == store_id,
                EventRow.zone_id == "BILLING",
                EventRow.event_type == "BILLING_QUEUE_JOIN",
                EventRow.is_staff == False,  # noqa: E712
                EventRow.timestamp >= now - timedelta(minutes=10),
            )
            .scalar()
            or 0
        )

    joins = (
        db.query(func.count(EventRow.event_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "BILLING_QUEUE_JOIN",
            EventRow.is_staff == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    abandons = (
        db.query(func.count(EventRow.event_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "BILLING_QUEUE_ABANDON",
            EventRow.is_staff == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    if joins == 0:
        abandonment_rate = 1.0 if abandons > 0 else 0.0
    else:
        abandonment_rate = float(abandons) / float(joins)

    return MetricsResponse(
        store_id=store_id,
        unique_visitors=int(unique_visitors),
        conversion_rate=round(conversion_rate, 4),
        avg_dwell_per_zone=avg_dwell_per_zone,
        queue_depth=int(queue_depth),
        abandonment_rate=round(abandonment_rate, 4),
    )
