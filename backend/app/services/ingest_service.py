"""
Ingest orchestration — UC1.
Coordinates fetching from a provider adapter and storing into MongoDB.
Records provenance in ingest_log collection.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from app.db.database import ingest_log_col
from app.services.timeseries_service import insert_time_series_batch
from app.services.asset_service import get_asset_detail
from app.services.datasource_service import get_data_source
from app.data_ingest.nasdaq_adapter import fetch_nasdaq_timeseries
from app.data_ingest.bloomberg_adapter import fetch_bloomberg_timeseries
from app.schemas.api import IngestRequest, IngestResponse
from app.core.logging import get_logger

logger = get_logger(__name__)

PROVIDER_ADAPTERS = {
    "nasdaq": fetch_nasdaq_timeseries,
    "bloomberg": fetch_bloomberg_timeseries,
}


async def run_ingest(req: IngestRequest) -> IngestResponse:
    """
    Main ingest entry point.
    1. Validate asset and source exist.
    2. Determine which adapter to use.
    3. Fetch records.
    4. Bulk insert (deduplicating by date).
    5. Write ingest log.
    """
    log_id = f"log_{uuid.uuid4().hex[:12]}"
    log_col = ingest_log_col()

    # Verify asset exists
    asset = await get_asset_detail(req.asset_id)
    if not asset:
        return IngestResponse(
            log_id=log_id, asset_id=req.asset_id, source_id=req.source_id,
            status="error", records_inserted=0,
            message=f"Asset {req.asset_id} not found",
        )

    # Verify source exists
    source = await get_data_source(req.source_id)
    if not source:
        return IngestResponse(
            log_id=log_id, asset_id=req.asset_id, source_id=req.source_id,
            status="error", records_inserted=0,
            message=f"Data source {req.source_id} not found",
        )

    # Find adapter
    adapter_key = source.provider_name.lower().split()[0]  # "Nasdaq Data Link" → "nasdaq"
    adapter = PROVIDER_ADAPTERS.get(adapter_key)
    if not adapter:
        return IngestResponse(
            log_id=log_id, asset_id=req.asset_id, source_id=req.source_id,
            status="error", records_inserted=0,
            message=f"No adapter for provider '{source.provider_name}'",
        )

    # Write "running" log
    log_doc = {
        "_id": log_id,
        "log_id": log_id,
        "source_id": req.source_id,
        "asset_id": req.asset_id,
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "records_inserted": 0,
        "status": "running",
        "error_message": "",
    }
    await log_col.insert_one(log_doc)

    try:
        records = await adapter(
            symbol=asset.symbol,
            asset_id=req.asset_id,
            source_id=req.source_id,
            from_date=req.from_date,
            to_date=req.to_date,
        )
        inserted = await insert_time_series_batch(records)
        status = "success"
        msg = f"Ingested {inserted} new records from {source.provider_name}"
        error_msg = ""
    except Exception as exc:
        inserted = 0
        status = "error"
        msg = str(exc)
        error_msg = str(exc)
        logger.exception(f"Ingest failed for {req.asset_id}/{req.source_id}")

    # Update log
    await log_col.update_one(
        {"_id": log_id},
        {"$set": {
            "finished_at": datetime.now(timezone.utc),
            "records_inserted": inserted,
            "status": status,
            "error_message": error_msg,
        }},
    )

    return IngestResponse(
        log_id=log_id,
        asset_id=req.asset_id,
        source_id=req.source_id,
        status=status,
        records_inserted=inserted,
        message=msg,
    )


async def get_ingest_logs(asset_id: str | None = None, limit: int = 20) -> list[dict]:
    col = ingest_log_col()
    query = {}
    if asset_id:
        query["asset_id"] = asset_id
    results = []
    async for doc in col.find(query, sort=[("started_at", -1)], limit=limit):
        doc.pop("_id", None)
        results.append(doc)
    return results
