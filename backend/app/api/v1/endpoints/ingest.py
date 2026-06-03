from fastapi import APIRouter, Query
from typing import Optional
from app.services.ingest_service import run_ingest, get_ingest_logs
from app.schemas.api import IngestRequest, IngestResponse

router = APIRouter(prefix="/ingest", tags=["Data Ingest (UC1)"])


@router.post("/", response_model=IngestResponse, summary="Trigger data ingest")
async def trigger_ingest(req: IngestRequest):
    """
    UC1 — Import data from an external provider for a given asset.
    Provider is determined by the data source's provider_name.
    Supported: 'nasdaq', 'bloomberg'.
    Provenance (source_id, timestamps) is recorded for every ingested record.
    """
    return await run_ingest(req)


@router.get("/logs", summary="Ingest audit log")
async def ingest_logs(
    asset_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Return recent ingest log entries for auditability."""
    return await get_ingest_logs(asset_id=asset_id, limit=limit)
