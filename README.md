# Purplle Store Intelligence System

Production-ready store analytics pipeline for **Brigade Road, Bangalore** (`STORE_BLR_002`): CCTV person detection → structured events → REST API → live dashboard.

## Quick Start (5 commands)

```bash
git clone <your-repo-url>
cd store-intelligence
cp /path/to/videos/*.mp4 data/videos/
docker compose up --build
# Visit http://localhost:3000 for dashboard, http://localhost:8000/docs for API
```

Place `Brigade_Bangalore_10_April_26.csv` in `data/` before first run to seed POS transactions.

## How to run detection pipeline

```bash
# With Docker (after API is up)
docker compose --profile pipeline run --rm pipeline

# Or locally
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
set PYTHONPATH=.
python -m pipeline.detect --api-url http://localhost:8000
```

Videos required: `data/videos/CAM_1.mp4` … `CAM_5.mp4`. Output: `data/events.jsonl`.

## How to run tests

```bash
docker compose run --rm api pytest tests/ -v --cov=app
# Or locally:
pytest tests/ -v --cov=app --cov=pipeline
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/events/ingest` | Batch ingest (≤500), idempotent |
| GET | `/stores/STORE_BLR_002/metrics` | Visitors, conversion, dwell, queue |
| GET | `/stores/STORE_BLR_002/funnel` | Entry → Zone → Billing → Purchase |
| GET | `/stores/STORE_BLR_002/heatmap` | Zone intensity 0–100 |
| GET | `/stores/STORE_BLR_002/anomalies` | Spike, conversion drop, dead zone |
| GET | `/health` | Service health + stale feed |

## Project Structure

```
store-intelligence/
├── pipeline/     # YOLOv8 + ByteTrack detection
├── app/            # FastAPI intelligence API
├── dashboard/      # Live web UI (port 3000)
├── tests/          # pytest suite (70%+ coverage target)
├── data/           # layout JSON, CSV, videos (gitignored)
└── docs/           # DESIGN.md, CHOICES.md
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_URL` | `http://api:8000` | Pipeline ingest target |
| `ENABLE_REPLAY` | `true` | Replay events.jsonl at 10× |
| `REPLAY_SPEED` | `10` | Replay multiplier |
| `SKIP_BOOTSTRAP` | `false` | Skip demo seed |



## License

Hackathon submission — Purplle Tech Challenge 2026.
