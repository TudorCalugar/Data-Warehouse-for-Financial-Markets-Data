"""Data Source / Provider service — temporal append, same rules as assets."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from app.db.database import data_sources_col
from app.models.documents import RecordStatus
from app.schemas.api import DataSourceCreateRequest, DataSourceSummary, DataSourceDetail
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_summary(doc: dict) -> DataSourceSummary:
    return DataSourceSummary(
        source_id=doc["source_id"],
        provider_name=doc["provider_name"],
        description=doc.get("description", ""),
        record_status=doc.get("record_status", "active"),
        valid_from=doc["valid_from"],
    )


def _to_detail(doc: dict) -> DataSourceDetail:
    return DataSourceDetail(
        source_id=doc["source_id"],
        provider_name=doc["provider_name"],
        description=doc.get("description", ""),
        base_url=doc.get("base_url", ""),
        api_version=doc.get("api_version", ""),
        supported_asset_classes=doc.get("supported_asset_classes", []),
        record_status=doc.get("record_status", "active"),
        valid_from=doc["valid_from"],
        extra=doc.get("extra", {}),
    )


async def list_data_sources(skip: int = 0, limit: int = 50) -> list[DataSourceSummary]:
    """Q3 — All active data sources (latest version per source_id)."""
    col = data_sources_col()
    pipeline = [
        {"$sort": {"source_id": 1, "valid_from": -1}},
        {"$group": {"_id": "$source_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$match": {"record_status": {"$ne": RecordStatus.DELETED.value}}},
        {"$skip": skip}, {"$limit": limit},
    ]
    results = []
    async for doc in col.aggregate(pipeline):
        results.append(_to_summary(doc))
    return results


async def get_data_source(source_id: str) -> DataSourceDetail | None:
    """Q4 — Full details of a data source."""
    col = data_sources_col()
    doc = await col.find_one(
        {"source_id": source_id},
        sort=[("valid_from", -1)],
    )
    return _to_detail(doc) if doc else None


async def create_data_source(req: DataSourceCreateRequest) -> DataSourceDetail:
    col = data_sources_col()
    source_id = f"src_{uuid.uuid4().hex[:10]}"
    doc = {
        "source_id": source_id,
        "provider_name": req.provider_name,
        "description": req.description,
        "base_url": req.base_url,
        "api_version": req.api_version,
        "supported_asset_classes": [c.value for c in req.supported_asset_classes],
        "record_status": RecordStatus.ACTIVE.value,
        "valid_from": datetime.now(timezone.utc),
        "extra": req.extra,
    }
    await col.insert_one(doc)
    logger.info(f"Data source created: {source_id} ({req.provider_name})")
    return _to_detail(doc)


async def get_or_create_source_by_name(provider_name: str) -> DataSourceDetail:
    """Used by ingest pipeline — idempotent."""
    col = data_sources_col()
    doc = await col.find_one(
        {"provider_name": provider_name},
        sort=[("valid_from", -1)],
    )
    if doc and doc.get("record_status") != RecordStatus.DELETED.value:
        return _to_detail(doc)
    # Create if missing
    return await create_data_source(DataSourceCreateRequest(
        provider_name=provider_name,
        description=f"Auto-registered: {provider_name}",
    ))
