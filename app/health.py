"""GET /health endpoint."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import check_db_connection, get_db
from app.models import EventRow, HealthResponse, STORE_ID

router = APIRouter()

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db_ok = check_db_connection()
    database = "connected" if db_ok else "unreachable"
    service = "healthy" if db_ok else "degraded"

    last_ts: Optional[datetime] = (
        db.query(func.max(EventRow.timestamp))
        .filter(EventRow.store_id == STORE_ID)
        .scalar()
    )
    last_event_timestamp = None
    stale_feed = True
    if last_ts:
        last_event_timestamp = last_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_feed = (datetime.utcnow() - last_ts) > timedelta(minutes=10)

    return HealthResponse(
        service=service,
        last_event_timestamp=last_event_timestamp,
        stale_feed=stale_feed,
        database=database,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
