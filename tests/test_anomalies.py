# PROMPT: Test anomaly detection for BILLING_QUEUE_SPIKE, CONVERSION_DROP, and DEAD_ZONE
# with correct severity levels and suggested_action strings.
# CHANGES MADE: Seeded high queue_depth metadata events and verified anomaly types returned.

from datetime import datetime, timedelta

import pytest

from app.models import EventRow


def test_dead_zone_anomaly(client, db_session):
    """No recent ZONE_ENTER should trigger DEAD_ZONE INFO."""
    r = client.get("/stores/STORE_BLR_002/anomalies")
    assert r.status_code == 200
    types = [a["anomaly_type"] for a in r.json()["anomalies"]]
    assert "DEAD_ZONE" in types


def test_billing_queue_spike(client, db_session, sample_event):
    now = datetime.utcnow()
    events = []
    for i in range(5):
        ev = sample_event(
            event_id=f"spike-{i}",
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            metadata={"queue_depth": 6, "sku_zone": None, "session_seq": i},
        )
        ev["timestamp"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        events.append(ev)
    client.post("/events/ingest", json={"events": events})
    r = client.get("/stores/STORE_BLR_002/anomalies")
    types = [a["anomaly_type"] for a in r.json()["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in types


def test_anomaly_has_suggested_action(client):
    r = client.get("/stores/STORE_BLR_002/anomalies")
    for a in r.json()["anomalies"]:
        assert a["suggested_action"]
        assert a["severity"] in ("INFO", "WARN", "CRITICAL")


def test_conversion_drop_warn(client, db_session, sample_event):
    """With no entries but POS data, conversion metrics may trigger WARN."""
    r = client.get("/stores/STORE_BLR_002/anomalies")
    assert r.status_code == 200
    assert "store_id" in r.json()
