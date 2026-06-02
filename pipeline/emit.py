"""Event schema validation and JSONL emission."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STORE_ID = "STORE_BLR_002"
VALID_EVENT_TYPES = {
    "ENTRY",
    "EXIT",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "REENTRY",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(
    *,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.0,
    metadata: Optional[dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")
    meta = {
        "queue_depth": None,
        "sku_zone": None,
        "session_seq": 1,
    }
    if metadata:
        meta.update(metadata)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp or utc_now_iso(),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(float(confidence), 4),
        "metadata": meta,
    }


class EventEmitter:
    """Append events to JSONL and optionally POST to API."""

    def __init__(self, output_path: Path, api_url: Optional[str] = None):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.api_url = api_url
        self._buffer: list[dict[str, Any]] = []
        self._session_seq: dict[str, int] = {}

    def next_session_seq(self, visitor_id: str) -> int:
        seq = self._session_seq.get(visitor_id, 0) + 1
        self._session_seq[visitor_id] = seq
        return seq

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        vid = event["visitor_id"]
        if "session_seq" not in event.get("metadata", {}):
            event["metadata"]["session_seq"] = self.next_session_seq(vid)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._buffer.append(event)
        return event

    def flush_to_api(self, batch_size: int = 100) -> int:
        if not self.api_url or not self._buffer:
            return 0
        import httpx

        sent = 0
        for i in range(0, len(self._buffer), batch_size):
            batch = self._buffer[i : i + batch_size]
            try:
                resp = httpx.post(
                    f"{self.api_url.rstrip('/')}/events/ingest",
                    json={"events": batch},
                    timeout=60.0,
                )
                if resp.status_code == 200:
                    sent += len(batch)
            except Exception:
                pass
        self._buffer.clear()
        return sent
