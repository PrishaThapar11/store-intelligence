"""Pydantic schemas and SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase

STORE_ID = "STORE_BLR_002"


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    event_id = Column(String(36), primary_key=True)
    store_id = Column(String(32), index=True)
    camera_id = Column(String(32))
    visitor_id = Column(String(16), index=True)
    event_type = Column(String(32), index=True)
    timestamp = Column(DateTime, index=True)
    zone_id = Column(String(32), nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    metadata_json = Column(Text, default="{}")
    queue_depth = Column(Integer, nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id = Column(String(36), primary_key=True)
    visitor_id = Column(String(16), index=True)
    store_id = Column(String(32), index=True)
    entry_time = Column(DateTime, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    converted = Column(Boolean, default=False)
    zones_visited = Column(Text, default="")
    is_staff = Column(Boolean, default=False)
    near_billing = Column(Boolean, default=False)


class POSTransactionRow(Base):
    __tablename__ = "pos_transactions"

    transaction_id = Column(String(64), primary_key=True)
    store_id = Column(String(32), index=True)
    timestamp = Column(DateTime, index=True)
    basket_value_inr = Column(Float, default=0.0)
    invoice_number = Column(String(64))
    brand_name = Column(String(128))
    salesperson_name = Column(String(128))


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 1


class StoreEvent(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = 0.0
    metadata: EventMetadata = Field(default_factory=EventMetadata)


class IngestRequest(BaseModel):
    events: list[StoreEvent]


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    store_id: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: dict[str, float]
    queue_depth: int
    abandonment_rate: float


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]


class HeatmapZone(BaseModel):
    zone_id: str
    visit_frequency: int
    avg_dwell_ms: float
    intensity: float


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[HeatmapZone]


class AnomalyItem(BaseModel):
    anomaly_type: str
    severity: str
    message: str
    suggested_action: str
    detected_at: str


class AnomaliesResponse(BaseModel):
    store_id: str
    anomalies: list[AnomalyItem]


class HealthResponse(BaseModel):
    service: str
    last_event_timestamp: Optional[str]
    stale_feed: bool
    database: str
    uptime_seconds: float
