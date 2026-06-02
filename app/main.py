"""FastAPI application entrypoint."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app import anomalies, database, funnel, health, heatmap, ingestion, metrics
from app.database import check_db_connection, init_db
from app.bootstrap import bootstrap_if_empty
from app.replay import start_replay_thread

logger = logging.getLogger("store_intelligence")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.handlers = [_handler]
logger.setLevel(logging.INFO)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "payload", None)
        if payload:
            return json.dumps(payload)
        return super().format(record)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if os.environ.get("SKIP_BOOTSTRAP", "").lower() not in ("1", "true", "yes"):
        bootstrap_if_empty()
    start_replay_thread()
    yield


app = FastAPI(
    title="Purplle Store Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion.router, tags=["ingestion"])
app.include_router(metrics.router, tags=["metrics"])
app.include_router(funnel.router, tags=["funnel"])
app.include_router(heatmap.router, tags=["heatmap"])
app.include_router(anomalies.router, tags=["anomalies"])
app.include_router(health.router, tags=["health"])


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    start = time.perf_counter()
    store_id = None
    event_count = None

    try:
        response = await call_next(request)
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "error": "SERVICE_UNAVAILABLE",
                "message": "Database unreachable",
                "retry_after": 30,
            },
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    if request.url.path.startswith("/stores/"):
        parts = request.url.path.split("/")
        if len(parts) > 2:
            store_id = parts[2]

    log_payload = {
        "trace_id": trace_id,
        "store_id": store_id or "STORE_BLR_002",
        "endpoint": request.url.path,
        "latency_ms": latency_ms,
        "event_count": event_count,
        "status_code": response.status_code,
    }
    record = logging.LogRecord(
        name="store_intelligence",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    record.payload = log_payload
    logger.handle(record)
    return response


@app.exception_handler(SQLAlchemyError)
async def db_exception_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=503,
        content={
            "error": "SERVICE_UNAVAILABLE",
            "message": "Database unreachable",
            "retry_after": 30,
        },
    )


@app.get("/")
def root():
    return {
        "service": "Purplle Store Intelligence",
        "store_id": "STORE_BLR_002",
        "docs": "/docs",
    }
