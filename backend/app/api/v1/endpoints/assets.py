from fastapi import APIRouter, Query, HTTPException, status
from datetime import datetime
from typing import Optional
from app.services import asset_service
from app.schemas.api import (
    AssetSummary, AssetDetail, AssetCreateRequest, AssetUpdateRequest
)

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.get("/", response_model=list[AssetSummary], summary="Q1 — List all assets")
async def list_assets(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    asset_class: Optional[str] = Query(None, description="Filter: stock, bond, crypto, …"),
):
    """Return identification data for all currently active financial assets."""
    return await asset_service.list_assets(skip=skip, limit=limit, asset_class=asset_class)


@router.get("/{asset_id}", response_model=AssetDetail, summary="Q2 — Get asset details")
async def get_asset(
    asset_id: str,
    as_of: Optional[datetime] = Query(None, description="Point-in-time query (ISO datetime)"),
):
    """Return full details of an asset. Use `as_of` for historical state."""
    asset = await asset_service.get_asset_detail(asset_id, as_of=as_of)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    return asset


@router.get("/{asset_id}/history", response_model=list[AssetDetail], summary="Temporal audit trail")
async def get_asset_history(asset_id: str):
    """Return ALL versions of an asset — full temporal history."""
    return await asset_service.get_asset_history(asset_id)


@router.post("/", response_model=AssetDetail, status_code=status.HTTP_201_CREATED)
async def create_asset(req: AssetCreateRequest):
    """Register a new financial instrument."""
    return await asset_service.create_asset(req)


@router.patch("/{asset_id}", response_model=AssetDetail)
async def update_asset(asset_id: str, req: AssetUpdateRequest):
    """
    Temporal update — inserts a new version.
    The old version is preserved unchanged.
    """
    asset = await asset_service.update_asset(asset_id, req)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(asset_id: str):
    """
    Temporal deletion — inserts a 'deleted' marker record.
    No data is removed from the database.
    """
    success = await asset_service.delete_asset(asset_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
