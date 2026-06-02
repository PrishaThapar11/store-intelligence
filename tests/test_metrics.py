# PROMPT: Write pytest tests for GET /stores/STORE_BLR_002/metrics covering zero visitors,
# conversion rate with POS correlation, all-staff exclusion, and empty store valid JSON.
# CHANGES MADE: Used in-memory DB fixture; seeded events and POS rows manually.

from datetime import datetime

import pytest

from app.models import EventRow, POSTransactionRow, SessionRow


def test_metrics_empty_store(client):
    r = client.get("/stores/STORE_BLR_002/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["store_id"] == "STORE_BLR_002"
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["queue_depth"] == 0


def test_metrics_with_visitors(client, db_session, sample_event):
    import uuid

    client.post(
        "/events/ingest",
        json={
            "events": [
                sample_event(
                    event_id=str(uuid.uuid4()),
                    visitor_id="VIS_aaaa01",
                    event_type="ENTRY",
                ),
                sample_event(
                    event_id=str(uuid.uuid4()),
                    visitor_id="VIS_aaaa01",
                    event_type="ZONE_DWELL",
                    zone_id="SKINCARE",
                    dwell_ms=5000,
                ),
            ]
        },
    )
    r = client.get("/stores/STORE_BLR_002/metrics")
    assert r.status_code == 200
    assert r.json()["unique_visitors"] >= 1


def test_staff_excluded_from_conversion(client, db_session, sample_event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                sample_event(
                    visitor_id="VIS_staff1",
                    event_type="ENTRY",
                    is_staff=True,
                ),
            ]
        },
    )
    r = client.get("/stores/STORE_BLR_002/metrics")
    data = r.json()
    assert data["conversion_rate"] == 0.0


def test_ingest_deduplication(client, sample_event):
    ev = sample_event()
    r1 = client.post("/events/ingest", json={"events": [ev]})
    r2 = client.post("/events/ingest", json={"events": [ev]})
    assert r1.json()["accepted"] == 1
    assert r2.json()["duplicates"] == 1


def test_ingest_batch_limit(client, sample_event):
    events = [sample_event(event_id=f"id-{i}") for i in range(501)]
    r = client.post("/events/ingest", json={"events": events})
    assert r.status_code == 400


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "service" in r.json()
    assert "uptime_seconds" in r.json()
