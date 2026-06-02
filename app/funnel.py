"""GET /stores/{store_id}/funnel with session deduplication."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EventRow, FunnelResponse, FunnelStage, SessionRow, STORE_ID

router = APIRouter()


@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
def get_funnel(store_id: str, db: Session = Depends(get_db)) -> FunnelResponse:
    if store_id != STORE_ID:
        store_id = STORE_ID

    entry_visitors = (
        db.query(func.distinct(EventRow.visitor_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type.in_(["ENTRY", "REENTRY"]),
            EventRow.is_staff == False,  # noqa: E712
        )
        .all()
    )
    stage1 = len([v[0] for v in entry_visitors])

    zone_visitors = (
        db.query(func.distinct(EventRow.visitor_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "ZONE_ENTER",
            EventRow.is_staff == False,  # noqa: E712
        )
        .all()
    )
    stage2 = len([v[0] for v in zone_visitors])

    billing_visitors = (
        db.query(func.distinct(EventRow.visitor_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "BILLING_QUEUE_JOIN",
            EventRow.is_staff == False,  # noqa: E712
        )
        .all()
    )
    stage3 = len([v[0] for v in billing_visitors])

    stage4 = (
        db.query(func.count(SessionRow.session_id))
        .filter(
            SessionRow.store_id == store_id,
            SessionRow.is_staff == False,  # noqa: E712
            SessionRow.converted == True,  # noqa: E712
        )
        .scalar()
        or 0
    )

    def drop_off(curr: int, prev: int) -> float:
        if prev <= 0:
            return 0.0
        return round(100.0 * (prev - curr) / prev, 2)

    stages = [
        FunnelStage(stage="Entry", count=stage1, drop_off_pct=0.0),
        FunnelStage(stage="Zone Visit", count=stage2, drop_off_pct=drop_off(stage2, stage1)),
        FunnelStage(
            stage="Billing Queue",
            count=stage3,
            drop_off_pct=drop_off(stage3, stage2),
        ),
        FunnelStage(
            stage="Purchase",
            count=stage4,
            drop_off_pct=drop_off(stage4, stage3),
        ),
    ]

    return FunnelResponse(store_id=store_id, stages=stages)
