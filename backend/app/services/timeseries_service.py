"""
Time series service.
All writes are pure appends — no update, no delete.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from app.db.database import time_series_col
from app.schemas.api import TimeSeriesPoint, TimeSeriesResponse
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_point(doc: dict) -> TimeSeriesPoint:
    return TimeSeriesPoint(
        ts_id=doc["ts_id"],
        asset_id=doc["asset_id"],
        source_id=doc["source_id"],
        series_date=doc["series_date"],
        ingested_at=doc.get("ingested_at", doc["series_date"]),
        open=doc.get("open"),
        high=doc.get("high"),
        low=doc.get("low"),
        close=doc.get("close"),
        volume=doc.get("volume"),
        indicators=doc.get("indicators", {}),
        raw_source_ref=doc.get("raw_source_ref", ""),
    )


async def get_time_series(
    asset_id: str,
    source_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 500,
    skip: int = 0,
) -> TimeSeriesResponse:
    """Q5 — Retrieve time series for an asset / source combination."""
    col = time_series_col()
    match: dict = {"asset_id": asset_id, "source_id": source_id}
    if from_date or to_date:
        date_filter: dict = {}
        if from_date:
            date_filter["$gte"] = from_date
        if to_date:
            date_filter["$lte"] = to_date
        match["series_date"] = date_filter

    cursor = col.find(match, sort=[("series_date", 1)]).skip(skip).limit(limit)
    data = [_to_point(doc) async for doc in cursor]

    return TimeSeriesResponse(
        asset_id=asset_id,
        source_id=source_id,
        from_date=from_date,
        to_date=to_date,
        count=len(data),
        data=data,
    )


async def insert_time_series_batch(records: list[dict]) -> int:
    """
    Bulk insert of time series records.
    Deduplicates by (asset_id, source_id, series_date) — skips existing dates.
    Returns number of actually inserted records.
    """
    col = time_series_col()
    if not records:
        return 0

    # Fetch existing dates for this asset+source to avoid duplicates
    asset_id = records[0]["asset_id"]
    source_id = records[0]["source_id"]
    existing_dates = set()
    async for doc in col.find(
        {"asset_id": asset_id, "source_id": source_id},
        {"series_date": 1, "_id": 0},
    ):
        existing_dates.add(doc["series_date"])

    now = datetime.now(timezone.utc)
    to_insert = []
    for r in records:
        if r["series_date"] not in existing_dates:
            r.setdefault("ts_id", f"ts_{uuid.uuid4().hex[:16]}")
            r.setdefault("ingested_at", now)
            to_insert.append(r)

    if not to_insert:
        logger.info("No new records to insert (all already present)")
        return 0

    await col.insert_many(to_insert, ordered=False)
    logger.info(f"Inserted {len(to_insert)} time series records for {asset_id}/{source_id}")
    return len(to_insert)
