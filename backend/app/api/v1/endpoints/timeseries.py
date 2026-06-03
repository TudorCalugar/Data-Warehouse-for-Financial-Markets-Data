from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional
from app.services.timeseries_service import get_time_series
from app.schemas.api import TimeSeriesResponse

router = APIRouter(prefix="/timeseries", tags=["Time Series"])


@router.get("/", response_model=TimeSeriesResponse, summary="Q5 — Get time series data")
async def get_ts(
    asset_id: str = Query(..., description="Asset identifier"),
    source_id: str = Query(..., description="Data source identifier"),
    from_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    to_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    limit: int = Query(500, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    """
    Q5 — Return time-series data for a specified asset and data source.
    Supports pagination and date range filtering.
    """
    result = await get_time_series(
        asset_id=asset_id,
        source_id=source_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        skip=skip,
    )
    if result.count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No time series data for asset={asset_id} source={source_id}",
        )
    return result
