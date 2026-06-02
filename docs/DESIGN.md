# Store Intelligence System — Design Document

## 1. System Overview

The Store Intelligence System transforms offline CCTV footage and POS transactions into actionable retail analytics for Purplle’s Brigade Road, Bangalore store (`STORE_BLR_002`). The architecture follows a classic lambda-style batch-to-serving pattern: a computer-vision pipeline emits structured events, a FastAPI service ingests and aggregates them, and a static dashboard polls REST endpoints for live visualization.

```
┌─────────────┐     JSONL + HTTP      ┌──────────────────┐
│  CCTV Clips │ ──► Detection Pipeline │  events.jsonl    │
│  CAM_1..5   │     (YOLOv8+ByteTrack) └────────┬─────────┘
└─────────────┘                                │
                                               ▼ POST /events/ingest
                                      ┌──────────────────┐
                                      │  FastAPI + SQLite │
                                      │  metrics/funnel/  │
                                      │  heatmap/anomaly  │
                                      └────────┬─────────┘
                                               │ GET (5s poll)
                                               ▼
                                      ┌──────────────────┐
                                      │  Web Dashboard    │
                                      │  localhost:3000   │
                                      └──────────────────┘
        Brigade_Bangalore CSV ──seed──► pos_transactions
```

## 2. Detection Pipeline Design

The pipeline (`pipeline/detect.py`) processes five synchronized store cameras mapped in `data/store_layout.json`. **YOLOv8m** detects persons (COCO class 0) at confidence **0.3** to satisfy the partial-occlusion requirement—low-confidence detections are retained with their true scores rather than filtered silently.

**ByteTrack** (via Ultralytics `tracker="bytetrack.yaml"`) maintains persistent `track_id` values per clip. Each track maps to a `visitor_id` via `VIS_` + 6 hex chars from MD5(`camera_id + track_id + date`). This is deterministic per day/camera, aiding reproducibility for judges.

**CAM_ENTRY_03** implements a horizontal tripwire at **y=540**. Centroid crossing from below to above (decreasing y) emits **ENTRY**; crossing upward emits **EXIT**. **Re-entry** uses HSV full-box histograms correlated via Pearson coefficient; matches above **0.85** within **30 minutes** of a prior EXIT emit **REENTRY** instead of inflating unique visitor counts.

**Staff handling**: CAM_BACK_04 forces `is_staff=True`. CAM_FLOOR_01/02 apply torso HSV heuristics (S&lt;50, V&lt;80 on &gt;60% pixels). Staff events are stored but excluded from customer metrics.

**Zone cameras** emit ZONE_ENTER on first detection, ZONE_DWELL every 30 continuous seconds, and billing queue JOIN/ABANDON based on normalized bounding-box centroids inside the billing ROI on CAM_BILLING_05.

## 3. Event Schema Rationale

Events are immutable facts with UUID `event_id` for idempotent ingestion. `session_seq` orders events within a visitor journey for debugging and funnel forensics. `dwell_ms=0` marks instantaneous transitions (ENTRY/EXIT/ZONE_ENTER). `metadata.queue_depth` carries billing congestion snapshots. The schema maps 1:1 to SQL columns plus a JSON metadata blob for extensibility without migrations.

## 4. API Architecture and Storage

**FastAPI** provides OpenAPI docs, async middleware, and Pydantic validation. **SQLite** (`data/store_intelligence.db`) suits single-store hackathon scope: zero ops overhead, file-mounted volume in Docker, adequate for thousands of events/minute.

Core tables: `events`, `sessions`, `pos_transactions`. Ingestion uses `INSERT` with pre-check deduplication by `event_id`. Sessions open on ENTRY/REENTRY, close on EXIT, and mark `converted` when billing-zone presence falls within five minutes of a seeded POS timestamp.

Endpoints compute metrics dynamically—no hardcoded responses—satisfying integrity checks.

## 5. AI-Assisted Decisions

**Example 1 — Tracker choice**: GPT suggested DeepSORT with appearance embeddings. I chose **ByteTrack** because Ultralytics integrates it natively, reducing dependency risk on a clean Docker machine, and Brigade Road clips have moderate crowd density where motion-first association suffices.

**Example 2 — Tripwire vs line-crossing polygon**: AI proposed a polygon ROI at the door. I disagreed and used a **single horizontal line** at y=540 because CAM_3’s glass door alignment is predominantly vertical motion in frame; a line is easier to audit on video and matches the problem statement literally.

**Example 3 — Conversion attribution**: AI wanted SKU-level basket matching. I chose **time-window correlation** (billing zone ±5 min of POS) because the provided CSV lacks per-visitor IDs—only timestamps and amounts—so SKU matching would be fabricated accuracy.

## 6. Known Limitations

- **Cross-camera identity**: Same person on CAM_1 and CAM_3 receives different `visitor_id` unless Re-ID fires on re-entry at the same camera.
- **Zone polygons**: Floor cameras assign zones by camera default, not pixel polygons—acceptable for hackathon clips where each camera maps to one primary zone.
- **Historical timestamps**: Video events use 2026-04-10; metrics “last 24h” uses wall-clock unless replay/bootstrap adjusts timestamps.
- **YOLO cold start**: First `docker compose run pipeline` downloads weights (~50MB)—documented in README.

Graceful degradation: empty DB returns zeros; DB errors return HTTP 503 JSON; health reports `STALE_FEED` when no events for ten minutes.

## 7. Deployment

`docker compose up` launches API (8000) and dashboard (3000). Bootstrap seeds demo events if empty. Optional `pipeline` profile processes videos when placed in `data/videos/`. Replay thread re-ingests `events.jsonl` at 10× speed for live dashboard bonus.
