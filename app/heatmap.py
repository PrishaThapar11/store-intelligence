"""GET /stores/{store_id}/heatmap — zone visit frequency normalized 0-100."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EventRow, HeatmapResponse, HeatmapZone, STORE_ID

router = APIRouter()

ZONE_IDS = ["ENTRY_EXIT", "SKINCARE", "MAKEUP", "HAIRCARE", "BILLING", "STOCKROOM"]


@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def get_heatmap(store_id: str, db: Session = Depends(get_db)) -> HeatmapResponse:
    if store_id != STORE_ID:
        store_id = STORE_ID

    stats: dict[str, dict] = {z: {"visits": 0, "dwell_sum": 0, "dwell_count": 0} for z in ZONE_IDS}

    enter_rows = (
        db.query(EventRow.zone_id, func.count(EventRow.event_id))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type.in_(["ZONE_ENTER", "ENTRY"]),
            EventRow.is_staff == False,  # noqa: E712
        )
        .group_by(EventRow.zone_id)
        .all()
    )
    for zone_id, cnt in enter_rows:
        if zone_id and zone_id in stats:
            stats[zone_id]["visits"] = int(cnt)

    dwell_rows = (
        db.query(EventRow.zone_id, func.avg(EventRow.dwell_ms))
        .filter(
            EventRow.store_id == store_id,
            EventRow.event_type == "ZONE_DWELL",
            EventRow.is_staff == False,  # noqa: E712
        )
        .group_by(EventRow.zone_id)
        .all()
    )
    for zone_id, avg_dwell in dwell_rows:
        if zone_id and zone_id in stats:
            stats[zone_id]["avg_dwell"] = float(avg_dwell or 0)

    max_visits = max((s["visits"] for s in stats.values()), default=1) or 1

    zones = []
    for zid in ZONE_IDS:
        s = stats[zid]
        visits = s["visits"]
        avg_dwell = s.get("avg_dwell", 0.0)
        intensity = round(100.0 * visits / max_visits, 2) if max_visits else 0.0
        zones.append(
            HeatmapZone(
                zone_id=zid,
                visit_frequency=visits,
                avg_dwell_ms=avg_dwell,
                intensity=intensity,
            )
        )

    return HeatmapResponse(store_id=store_id, zones=zones)
