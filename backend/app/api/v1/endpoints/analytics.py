from fastapi import APIRouter, Query
from datetime import datetime
from typing import Optional
from app.services.analytics_service import get_stats, forecast_price, compare_assets, get_export_data
from app.schemas.api import StatsSummary, ForecastResponse, CompareResponse

router = APIRouter(prefix="/analytics", tags=["Analytics (UC3)"])


@router.get("/stats", response_model=StatsSummary, summary="Summary statistics")
async def stats(
    asset_id: str = Query(...),
    source_id: str = Query(...),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
):
    """
    Return summary statistics for a time series:
    count, min/max/avg/std close, total volume, price change %.
    """
    return await get_stats(asset_id, source_id, from_date, to_date)


@router.get("/forecast", response_model=ForecastResponse, summary="Price forecast")
async def forecast(
    asset_id: str = Query(...),
    source_id: str = Query(...),
    horizon_days: int = Query(5, ge=1, le=30, description="Trading days to forecast"),
):
    """
    Forecast next N trading days close price using linear regression on the last 60 data points.
    Returns predicted close with 90% confidence interval.
    """
    return await forecast_price(asset_id, source_id, horizon_days)


@router.get("/compare", response_model=CompareResponse, summary="Compare multiple assets")
async def compare(
    asset_ids: str = Query(..., description="Comma-separated list of asset_ids"),
    source_id: str = Query(...),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
):
    """
    Compare multiple assets: Pearson correlation matrix + individual statistics.
    """
    ids = [a.strip() for a in asset_ids.split(",") if a.strip()]
    return await compare_assets(ids, source_id, from_date, to_date)


@router.get("/export", summary="Export flat data for Spark / pandas")
async def export(
    asset_id: str = Query(...),
    source_id: str = Query(...),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(5000, ge=1, le=50000),
):
    """
    Return flat JSON records suitable for Apache Spark / pandas processing.
    Indicators are denormalised into top-level fields with 'ind_' prefix.
    """
    return await get_export_data(asset_id, source_id, from_date, to_date, limit)
