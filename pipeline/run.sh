#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
export API_URL="${API_URL:-http://api:8000}"
echo "Store Intelligence Detection Pipeline"
echo "Videos directory: ${ROOT}/data/videos"
echo "Output: ${ROOT}/data/events.jsonl"
python -m pipeline.detect --api-url "$API_URL"
echo "Done. Events at data/events.jsonl"
