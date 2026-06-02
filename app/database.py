"""SQLite setup, session factory, and POS CSV seed loader."""
from __future__ import annotations

import csv
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, POSTransactionRow

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "store_intelligence.db"
CSV_PATH = ROOT / "data" / "Brigade_Bangalore_10_April_26.csv"
STORE_ID = "STORE_BLR_002"

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_session_factory():
    get_engine()
    return _SessionLocal


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    seed_pos_transactions()


def check_db_connection() -> bool:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def ist_to_utc(order_date: str, order_time: str) -> datetime:
    """Convert IST date/time strings to UTC datetime."""
    # order_date: 10-04-2026, order_time: HH:MM:SS
    parts = order_date.strip().split("-")
    if len(parts) == 3:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        year, month, day = 2026, 4, 10
    tparts = order_time.strip().split(":")
    h = int(tparts[0]) if len(tparts) > 0 else 0
    m = int(tparts[1]) if len(tparts) > 1 else 0
    s = int(tparts[2]) if len(tparts) > 2 else 0
    ist = datetime(year, month, day, h, m, s, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return ist.astimezone(timezone.utc)


def seed_pos_transactions() -> None:
    csv_path = find_pos_csv()
    if csv_path is None:
        logger.warning("POS CSV not found at %s — skipping seed", CSV_PATH)
        return

    factory = get_session_factory()
    db = factory()
    try:
        existing = db.query(POSTransactionRow).count()
        if existing > 0:
            return

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for idx, row in enumerate(rows, start=1):
            inv = row.get("invoice_number") or row.get("order_id") or str(uuid.uuid4())
            txn_id = f"{inv}:{row.get('order_id', '')}:{row.get('sku', '')}:{idx}"
            order_date = row.get("order_date", "10-04-2026")
            order_time = row.get("order_time", "12:00:00")
            try:
                ts = ist_to_utc(order_date, order_time)
            except Exception:
                ts = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
            try:
                basket = float(row.get("total_amount") or row.get("NMV") or 0)
            except (TypeError, ValueError):
                basket = 0.0

            db.add(
                POSTransactionRow(
                    transaction_id=txn_id,
                    store_id=STORE_ID,
                    timestamp=ts.replace(tzinfo=None),
                    basket_value_inr=basket,
                    invoice_number=str(inv),
                    brand_name=row.get("brand_name", ""),
                    salesperson_name=row.get("salesperson_name", ""),
                )
            )
        db.commit()
        logger.info("Seeded %d POS transactions", len(rows))
    except Exception as e:
        db.rollback()
        logger.error("Failed to seed POS: %s", e)
    finally:
        db.close()


def find_pos_csv() -> Optional[Path]:
    """Return the real POS CSV even if Windows added a download suffix."""
    if CSV_PATH.exists():
        return CSV_PATH

    data_dir = CSV_PATH.parent
    candidates = sorted(data_dir.glob("Brigade_Bangalore_10_April_26*.csv"))
    if candidates:
        return candidates[0]

    candidates = sorted(data_dir.glob("*Brigade*Bangalore*.csv"))
    return candidates[0] if candidates else None


def metadata_to_json(meta: dict) -> str:
    return json.dumps(meta or {})
