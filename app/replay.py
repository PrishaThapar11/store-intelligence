"""Replay events from JSONL at 10x speed for live dashboard bonus."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / "data" / "events.jsonl"
REPLAY_SPEED = float(os.environ.get("REPLAY_SPEED", "10"))


def _load_events() -> list[dict]:
    if not EVENTS_PATH.exists():
        return []
    events = []
    with open(EVENTS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events


def replay_events(api_url: str) -> None:
    events = _load_events()
    if not events:
        logger.info("No events.jsonl for replay — ingest pipeline output first")
        return

    logger.info("Replaying %d events at %sx speed", len(events), REPLAY_SPEED)
    prev_ts: datetime | None = None

    for ev in events:
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        except Exception:
            ts = None

        if prev_ts and ts:
            delta = (ts - prev_ts).total_seconds() / REPLAY_SPEED
            if delta > 0:
                time.sleep(min(delta, 2.0))

        try:
            httpx.post(
                f"{api_url.rstrip('/')}/events/ingest",
                json={"events": [ev]},
                timeout=30.0,
            )
        except Exception as e:
            logger.debug("Replay ingest skip: %s", e)

        prev_ts = ts

    logger.info("Replay complete")


def start_replay_thread() -> None:
    if os.environ.get("ENABLE_REPLAY", "true").lower() not in ("1", "true", "yes"):
        return

    api_url = os.environ.get("API_URL", "http://127.0.0.1:8000")

    def _run():
        time.sleep(3)
        replay_events(api_url)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
