"""
Async MongoDB connection via Motor.
Collections:
  - assets          : financial instruments (temporal — append-only)
  - data_sources    : registered data providers / vendors
  - time_series     : price / indicator records (temporal — append-only)
  - ingest_log      : audit log of every ingest run
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    global _client, _db
    settings = get_settings()
    logger.info("Connecting to MongoDB …")
    _client = AsyncIOMotorClient(settings.mongo_uri)
    _db = _client[settings.mongo_db_name]
    await _ensure_indexes()
    logger.info("MongoDB connected ✓")


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB disconnected")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call connect_db() first")
    return _db


# ── Collection helpers ────────────────────────────────────────────────────────

def assets_col():
    return get_db()["assets"]

def data_sources_col():
    return get_db()["data_sources"]

def time_series_col():
    return get_db()["time_series"]

def ingest_log_col():
    return get_db()["ingest_log"]


# ── Index creation ─────────────────────────────────────────────────────────────

async def _ensure_indexes() -> None:
    db = get_db()

    # assets: look up by symbol, filter by validity window
    await db["assets"].create_indexes([
        IndexModel([("symbol", ASCENDING), ("valid_from", DESCENDING)]),
        IndexModel([("asset_class", ASCENDING)]),
        IndexModel([("record_status", ASCENDING)]),
    ])

    # data_sources: unique provider name
    await db["data_sources"].create_indexes([
        IndexModel([("provider_name", ASCENDING)], unique=True),
    ])

    # time_series: compound index for the hot query path (Q5)
    await db["time_series"].create_indexes([
        IndexModel([
            ("asset_id", ASCENDING),
            ("source_id", ASCENDING),
            ("series_date", DESCENDING),
        ]),
        IndexModel([("ingested_at", DESCENDING)]),
    ])

    # ingest_log: audit trail sorted by time
    await db["ingest_log"].create_indexes([
        IndexModel([("started_at", DESCENDING)]),
    ])

    logger.info("MongoDB indexes ensured ✓")
