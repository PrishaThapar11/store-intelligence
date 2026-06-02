"""Pytest fixtures with in-memory SQLite."""
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["ENABLE_REPLAY"] = "false"
os.environ["SKIP_BOOTSTRAP"] = "true"

from app.database import get_db, init_db
from app.main import app
from app.models import Base, EventRow, POSTransactionRow, SessionRow


@pytest.fixture
def db_session():
    # Share one in-memory SQLite DB across app/test threads.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_event():
    def _make(**kwargs):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = {
            "event_id": kwargs.get("event_id", str(uuid.uuid4())),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": kwargs.get("visitor_id", "VIS_abc123"),
            "event_type": kwargs.get("event_type", "ENTRY"),
            "timestamp": kwargs.get("timestamp", now_iso),
            "zone_id": kwargs.get("zone_id", "ENTRY_EXIT"),
            "dwell_ms": kwargs.get("dwell_ms", 0),
            "is_staff": kwargs.get("is_staff", False),
            "confidence": kwargs.get("confidence", 0.91),
            "metadata": kwargs.get(
                "metadata",
                {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            ),
        }
        base.update({k: v for k, v in kwargs.items() if k != "metadata"})
        if "metadata" in kwargs:
            base["metadata"] = kwargs["metadata"]
        return base

    return _make
