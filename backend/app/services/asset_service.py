"""
Asset service — all writes are temporal appends.
No document is ever updated or deleted in-place.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from bson import ObjectId
from app.db.database import assets_col
from app.models.documents import AssetDocument, RecordStatus, AssetClass, Region
from app.schemas.api import AssetCreateRequest, AssetUpdateRequest, AssetSummary, AssetDetail
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_summary(doc: dict) -> AssetSummary:
    return AssetSummary(
        asset_id=doc["asset_id"],
        symbol=doc["symbol"],
        asset_class=doc["asset_class"],
        description=doc["description"],
        region=doc["region"],
        currency=doc.get("currency", "USD"),
        record_status=doc.get("record_status", "active"),
        valid_from=doc["valid_from"],
    )


def _to_detail(doc: dict) -> AssetDetail:
    return AssetDetail(
        asset_id=doc["asset_id"],
        symbol=doc["symbol"],
        asset_class=doc["asset_class"],
        description=doc["description"],
        region=doc["region"],
        currency=doc.get("currency", "USD"),
        record_status=doc.get("record_status", "active"),
        valid_from=doc["valid_from"],
        extra=doc.get("extra", {}),
        created_by=doc.get("created_by", "system"),
    )


async def _latest_version(asset_id: str, as_of: datetime | None = None) -> dict | None:
    """Return the most recent version of an asset at the given point in time."""
    col = assets_col()
    query: dict = {"asset_id": asset_id}
    if as_of:
        query["valid_from"] = {"$lte": as_of}
    doc = await col.find_one(query, sort=[("valid_from", -1)])
    return doc


# ── Public API ────────────────────────────────────────────────────────────────

async def list_assets(skip: int = 0, limit: int = 50, asset_class: str | None = None) -> list[AssetSummary]:
    """
    Q1 — Return summary for all *currently active* assets.
    For each logical asset_id, return only the latest non-deleted version.
    Uses aggregation pipeline to pick the latest record per asset_id.
    """
    col = assets_col()
    pipeline = [
        {"$sort": {"asset_id": 1, "valid_from": -1}},
        {"$group": {
            "_id": "$asset_id",
            "doc": {"$first": "$$ROOT"},
        }},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$match": {"record_status": {"$ne": RecordStatus.DELETED.value}}},
    ]
    if asset_class:
        pipeline.append({"$match": {"asset_class": asset_class}})
    pipeline += [{"$skip": skip}, {"$limit": limit}]

    results = []
    async for doc in col.aggregate(pipeline):
        results.append(_to_summary(doc))
    return results


async def get_asset_detail(asset_id: str, as_of: datetime | None = None) -> AssetDetail | None:
    """Q2 — Full details of an asset, optionally at a past point-in-time."""
    doc = await _latest_version(asset_id, as_of)
    if not doc:
        return None
    return _to_detail(doc)


async def create_asset(req: AssetCreateRequest) -> AssetDetail:
    """Insert first version of a new asset."""
    col = assets_col()
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    doc = {
        "asset_id": asset_id,
        "symbol": req.symbol.upper(),
        "asset_class": req.asset_class.value,
        "description": req.description,
        "region": req.region.value,
        "currency": req.currency,
        "record_status": RecordStatus.ACTIVE.value,
        "valid_from": datetime.now(timezone.utc),
        "extra": req.extra,
        "created_by": req.created_by,
    }
    await col.insert_one(doc)
    logger.info(f"Asset created: {asset_id} ({req.symbol})")
    return _to_detail(doc)


async def update_asset(asset_id: str, req: AssetUpdateRequest) -> AssetDetail | None:
    """
    Temporal update — fetch current version, apply changes, insert new version.
    Old version is preserved unchanged.
    """
    current = await _latest_version(asset_id)
    if not current or current.get("record_status") == RecordStatus.DELETED.value:
        return None

    new_doc = dict(current)
    new_doc.pop("_id", None)
    new_doc["valid_from"] = datetime.now(timezone.utc)

    if req.description is not None:
        new_doc["description"] = req.description
    if req.region is not None:
        new_doc["region"] = req.region.value
    if req.currency is not None:
        new_doc["currency"] = req.currency
    if req.extra is not None:
        new_doc["extra"] = {**new_doc.get("extra", {}), **req.extra}

    await assets_col().insert_one(new_doc)
    logger.info(f"Asset updated (new version): {asset_id}")
    return _to_detail(new_doc)


async def delete_asset(asset_id: str) -> bool:
    """
    Temporal deletion — insert a marker record with record_status = "deleted".
    No document is removed.
    """
    current = await _latest_version(asset_id)
    if not current or current.get("record_status") == RecordStatus.DELETED.value:
        return False

    marker = dict(current)
    marker.pop("_id", None)
    marker["valid_from"] = datetime.now(timezone.utc)
    marker["record_status"] = RecordStatus.DELETED.value

    await assets_col().insert_one(marker)
    logger.info(f"Asset logically deleted: {asset_id}")
    return True


async def get_asset_history(asset_id: str) -> list[AssetDetail]:
    """Return ALL versions of an asset (full temporal audit trail)."""
    col = assets_col()
    results = []
    async for doc in col.find({"asset_id": asset_id}, sort=[("valid_from", 1)]):
        results.append(_to_detail(doc))
    return results
