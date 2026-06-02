# Engineering Choices — Store Intelligence System

This document records three foundational decisions for the Purplle Tech Challenge 2026 submission, including alternatives considered, AI suggestions, and final rationale.

---

## Decision 1: Model Selection — YOLOv8m + ByteTrack

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **YOLOv8m** | Mature Ultralytics stack, ByteTrack built-in, strong person AP | Heavier than nano |
| YOLOv9 / YOLOv10 | Newer architectures | Less stable packaging in hackathon window |
| RT-DETR | Transformer accuracy | Heavier deps, slower CPU inference |
| MediaPipe Pose | Lightweight | Pose ≠ reliable occupancy counting at store scale |

### What AI suggested

Claude/GPT recommended **YOLOv8n** for speed or **RT-DETR** for accuracy on crowded scenes. For DeepSORT vs ByteTrack, AI leaned DeepSORT when “Re-ID quality is paramount.”

### What I chose

**YOLOv8m** with **ByteTrack** and confidence threshold **0.3**.

### Why

Brigade Road clips show **2–8 persons per frame**, not stadium crowds. YOLOv8m balances recall (important for conversion funnel completeness) with real-time-ish batch processing on a laptop GPU/CPU. ByteTrack excels when detection quality is reasonable—which YOLOv8m provides—without a separate embedding model download. DeepSORT would add another failure point during `docker compose` on a judge’s machine with no GPU.

Re-ID for **re-entry** is handled separately via HSV histogram correlation in `pipeline/tracker.py`, decoupling cross-session identity from frame-to-frame tracking. This matches the spec without over-engineering a full appearance database.

---

## Decision 2: Event Schema Design

### Options considered

- **Minimal schema** (type, time, person_id only) — simple but insufficient for zone dwell and queue metrics.
- **Protobuf/streaming bus** (Kafka) — production-grade but violates ten-minute reviewer setup.
- **Chosen rich JSON schema** with `dwell_ms`, `confidence`, `metadata.session_seq`, and typed `event_type` enum.

### What AI suggested

AI proposed nesting `visitor` and `location` objects and omitting `confidence` when below 0.5 to “reduce noise.”

### What I chose

Flat JSON events with **mandatory confidence**, explicit `zone_id`, and `metadata` for `queue_depth`, `sku_zone`, and `session_seq`.

### Why

**session_seq** gives ordered narratives per visitor for debugging disputed funnel counts. **confidence never suppressed** aligns with edge case #4—reviewers can filter downstream, but the pipeline must not hide uncertainty. **dwell_ms=0** for instantaneous events distinguishes transitions from ZONE_DWELL aggregates, simplifying SQL `AVG(dwell_ms) WHERE event_type='ZONE_DWELL'`.

The schema directly powers:

- `/metrics` → `avg_dwell_per_zone`, `queue_depth`, `abandonment_rate`
- `/funnel` → stage transitions by `event_type`
- `/heatmap` → `ZONE_ENTER` frequency
- `/anomalies` → billing queue depth in metadata

No over-engineering: no Avro registry, no nested optional blobs beyond `metadata`.

---

## Decision 3: Storage and API Architecture — SQLite + FastAPI

### Options considered

| Stack | Fit for hackathon | Fit for 40 stores |
|-------|-------------------|-------------------|
| SQLite + FastAPI | Excellent | Poor write concurrency |
| PostgreSQL + FastAPI | Good | Good |
| Flask + raw SQL | Faster bootstrap | Weaker validation |

### What AI suggested

“Use PostgreSQL even for MVP so you don’t rewrite later” and “Django admin for debugging.”

### What I chose

**SQLite** file DB with **SQLAlchemy ORM** and **FastAPI** routers split by domain (`metrics.py`, `funnel.py`, etc.).

### Why

Reviewers run **`docker compose up`** on a clean laptop. SQLite eliminates another container, port, and credentials. FastAPI gives Swagger at `/docs` for the 2-minute API verification window. Pydantic validates ingest batches (≤500) with partial success semantics.

### What breaks first at 40 live stores

1. **SQLite write lock** — 40 cameras × 30fps detections will serialize writes and stall ingest.
2. **Single API process** — CPU-bound aggregation on every GET under load.
3. **Histogram Re-ID in Python** — won't scale to thousands of simultaneous tracks.
4. **Disk-mounted JSONL replay** — not a real event bus.

### Production migration path

- **PostgreSQL** or **TimescaleDB** for events, partitioned by `store_id` and day.
- **Redis** for live `queue_depth` and dedupe cache.
- **S3 + Lambda/Kubernetes jobs** for video inference.
- **Kafka/PubSub** between pipeline and API.
- **Grafana** replacing custom HTML dashboard.

---

## Summary

Each choice optimizes for **reviewer time-to-value** and **schema compliance** while documenting a credible path to production. AI accelerated scaffolding; human judgment corrected over-scoped ideas (Kafka, SKU matching, polygon tripwires) in favor of spec-aligned, testable simplicity.
