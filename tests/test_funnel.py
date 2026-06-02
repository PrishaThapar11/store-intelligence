# PROMPT: Test funnel endpoint session deduplication for REENTRY visitors counted once,
# drop-off percentages, and zero purchase scenario.
# CHANGES MADE: Added explicit REENTRY pair tests and funnel stage ordering assertions.

import pytest


def test_funnel_zero_purchases(client, sample_event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                sample_event(visitor_id="VIS_f001", event_type="ENTRY"),
                sample_event(
                    visitor_id="VIS_f001",
                    event_type="ZONE_ENTER",
                    zone_id="MAKEUP",
                ),
            ]
        },
    )
    r = client.get("/stores/STORE_BLR_002/funnel")
    assert r.status_code == 200
    stages = {s["stage"]: s for s in r.json()["stages"]}
    assert stages["Purchase"]["count"] == 0


def test_funnel_reentry_counted_once(client, sample_event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                sample_event(visitor_id="VIS_re01", event_type="ENTRY"),
                sample_event(visitor_id="VIS_re01", event_type="EXIT"),
                sample_event(visitor_id="VIS_re01", event_type="REENTRY"),
            ]
        },
    )
    r = client.get("/stores/STORE_BLR_002/funnel")
    entry_count = r.json()["stages"][0]["count"]
    assert entry_count == 1


def test_funnel_drop_off_percentages(client, sample_event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                sample_event(visitor_id="VIS_d001", event_type="ENTRY"),
                sample_event(visitor_id="VIS_d002", event_type="ENTRY"),
                sample_event(
                    visitor_id="VIS_d001",
                    event_type="ZONE_ENTER",
                    zone_id="SKINCARE",
                ),
            ]
        },
    )
    r = client.get("/stores/STORE_BLR_002/funnel")
    stages = r.json()["stages"]
    assert stages[0]["count"] == 2
    assert stages[1]["count"] == 1
    assert stages[1]["drop_off_pct"] == 50.0


def test_heatmap_endpoint(client):
    r = client.get("/stores/STORE_BLR_002/heatmap")
    assert r.status_code == 200
    zones = r.json()["zones"]
    assert len(zones) == 6
    for z in zones:
        assert 0 <= z["intensity"] <= 100
