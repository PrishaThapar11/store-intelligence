"""GET /stores/{store_id}/anomalies detection."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.metrics import get_metrics
from app.models import AnomaliesResponse, AnomalyItem, EventRow, POSTransactionRow, STORE_ID

router = APIRouter()


@router.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)
def get_anomalies(store_id: str, db: Session = Depends(get_db)) -> AnomaliesResponse:
    if store_id != STORE_ID:
        store_id = STORE_ID

    now = datetime.utcnow()
    anomalies: list[AnomalyItem] = []
    detected_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    metrics = get_metrics(store_id, db)
    queue_depth = metrics.queue_depth

    # BILLING_QUEUE_SPIKE — check recent queue_depth events over 5 min window
    five_min_ago = now - timedelta(minutes=5)
    recent_depths = []
    rows = (
        db.query(EventRow)
        .filter(
            EventRow.store_id == store_id,
            EventRow.timestamp >= five_min_ago,
            EventRow.event_type == "BILLING_QUEUE_JOIN",
        )
        .order_by(EventRow.timestamp.desc())
        .limit(100)
        .all()
    )
    for r in rows:
        try:
            meta = json.loads(r.metadata_json or "{}")
            if meta.get("queue_depth") is not None:
                recent_depths.append(int(meta["queue_depth"]))
        except json.JSONDecodeError:
            pass
    max_depth = max(recent_depths + [queue_depth], default=0)
    sustained = max_depth > 3 and len(rows) >= 3

    if sustained:
        severity = "CRITICAL" if max_depth > 5 else "WARN"
        anomalies.append(
            AnomalyItem(
                anomaly_type="BILLING_QUEUE_SPIKE",
                severity=severity,
                message=f"Billing queue depth {max_depth} sustained >5 minutes",
                suggested_action="Deploy additional billing staff immediately",
                detected_at=detected_at,
            )
        )

    # CONVERSION_DROP — today vs 7-day average from POS
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = today_start - timedelta(days=7)

    daily_rates: list[float] = []
    for day_offset in range(7):
        day = seven_days_ago + timedelta(days=day_offset)
        day_end = day + timedelta(days=1)
        txn_count = (
            db.query(func.count(POSTransactionRow.transaction_id))
            .filter(
                POSTransactionRow.store_id == store_id,
                POSTransactionRow.timestamp >= day,
                POSTransactionRow.timestamp < day_end,
            )
            .scalar()
            or 0
        )
        entries = (
            db.query(func.count(func.distinct(EventRow.visitor_id)))
            .filter(
                EventRow.store_id == store_id,
                EventRow.event_type.in_(["ENTRY", "REENTRY"]),
                EventRow.timestamp >= day,
                EventRow.timestamp < day_end,
                EventRow.is_staff == False,  # noqa: E712
            )
            .scalar()
            or 0
        )
        rate = float(txn_count) / float(entries) if entries > 0 else 0.0
        daily_rates.append(rate)

    avg_rate = sum(daily_rates) / len(daily_rates) if daily_rates else 0.0
    today_rate = metrics.conversion_rate
    if avg_rate > 0 and today_rate < avg_rate * 0.8:
        anomalies.append(
            AnomalyItem(
                anomaly_type="CONVERSION_DROP",
                severity="WARN",
                message=f"Conversion rate {today_rate:.2%} below 7-day average {avg_rate:.2%}",
                suggested_action="Review staff engagement and product placement",
                detected_at=detected_at,
            )
        )

    # DEAD_ZONE — no ZONE_ENTER in last 30 minutes
    thirty_min_ago = now - timedelta(minutes=30)
    for zone_id in ["SKINCARE", "MAKEUP", "HAIRCARE", "BILLING", "ENTRY_EXIT"]:
        recent = (
            db.query(func.count(EventRow.event_id))
            .filter(
                EventRow.store_id == store_id,
                EventRow.zone_id == zone_id,
                EventRow.event_type.in_(["ZONE_ENTER", "ENTRY"]),
                EventRow.timestamp >= thirty_min_ago,
            )
            .scalar()
            or 0
        )
        if recent == 0:
            anomalies.append(
                AnomalyItem(
                    anomaly_type="DEAD_ZONE",
                    severity="INFO",
                    message=f"No activity in zone {zone_id} for 30+ minutes",
                    suggested_action="Check camera feed and consider promotional placement",
                    detected_at=detected_at,
                )
            )

    return AnomaliesResponse(store_id=store_id, anomalies=anomalies)
