"""
UC3 — Analytics and Data Mining.
Provides: summary statistics, trend detection, simple price forecasting,
multi-asset comparison, and a Spark-ready data export endpoint.
"""

from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
from app.db.database import time_series_col
from app.schemas.api import StatsSummary, ForecastResponse, ForecastPoint, CompareResponse
from app.core.logging import get_logger

logger = get_logger(__name__)


async def _fetch_closes(
    asset_id: str,
    source_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 2000,
) -> list[tuple[datetime, float]]:
    """Return (date, close) pairs sorted by date ASC."""
    col = time_series_col()
    match: dict = {
        "asset_id": asset_id,
        "source_id": source_id,
        "close": {"$ne": None},
    }
    if from_date or to_date:
        df: dict = {}
        if from_date:
            df["$gte"] = from_date
        if to_date:
            df["$lte"] = to_date
        match["series_date"] = df

    pairs = []
    async for doc in col.find(match, {"series_date": 1, "close": 1, "_id": 0},
                               sort=[("series_date", 1)], limit=limit):
        if doc.get("close") is not None:
            pairs.append((doc["series_date"], float(doc["close"])))
    return pairs


def _basic_stats(values: list[float]) -> dict:
    if not values:
        return {"min": None, "max": None, "avg": None, "std": None}
    n = len(values)
    mn = min(values)
    mx = max(values)
    avg = sum(values) / n
    variance = sum((v - avg) ** 2 for v in values) / n
    std = math.sqrt(variance)
    return {"min": mn, "max": mx, "avg": avg, "std": std}


async def get_stats(
    asset_id: str,
    source_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> StatsSummary:
    col = time_series_col()
    match: dict = {"asset_id": asset_id, "source_id": source_id}
    if from_date or to_date:
        df: dict = {}
        if from_date:
            df["$gte"] = from_date
        if to_date:
            df["$lte"] = to_date
        match["series_date"] = df

    # MongoDB aggregation for efficiency
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "min_close": {"$min": "$close"},
            "max_close": {"$max": "$close"},
            "avg_close": {"$avg": "$close"},
            "total_volume": {"$sum": "$volume"},
        }},
    ]
    result = None
    async for doc in col.aggregate(pipeline):
        result = doc

    if not result:
        return StatsSummary(
            asset_id=asset_id, source_id=source_id,
            from_date=from_date, to_date=to_date,
            count=0, min_close=None, max_close=None,
            avg_close=None, std_close=None, total_volume=None,
            price_change_pct=None,
        )

    # Compute std dev and price change separately
    pairs = await _fetch_closes(asset_id, source_id, from_date, to_date)
    closes = [p[1] for p in pairs]
    stats = _basic_stats(closes)
    price_change = None
    if len(closes) >= 2:
        price_change = round((closes[-1] - closes[0]) / closes[0] * 100, 4) if closes[0] else None

    return StatsSummary(
        asset_id=asset_id,
        source_id=source_id,
        from_date=from_date,
        to_date=to_date,
        count=result["count"],
        min_close=round(result["min_close"], 4) if result["min_close"] else None,
        max_close=round(result["max_close"], 4) if result["max_close"] else None,
        avg_close=round(result["avg_close"], 4) if result["avg_close"] else None,
        std_close=round(stats["std"], 4) if stats["std"] else None,
        total_volume=result.get("total_volume"),
        price_change_pct=price_change,
    )


async def forecast_price(
    asset_id: str,
    source_id: str,
    horizon_days: int = 5,
) -> ForecastResponse:
    """
    Simple linear trend + noise forecast (suitable for demo purposes).
    Production would use ARIMA / Prophet / ML models.
    Uses last 60 trading days as the regression window.
    """
    pairs = await _fetch_closes(asset_id, source_id, limit=60)
    if len(pairs) < 5:
        return ForecastResponse(
            asset_id=asset_id, source_id=source_id,
            method="linear_trend",
            horizon_days=horizon_days,
            last_known_close=None,
            forecast=[],
        )

    closes = [p[1] for p in pairs]
    n = len(closes)
    xs = list(range(n))

    # Linear regression: y = a + b*x
    x_mean = sum(xs) / n
    y_mean = sum(closes) / n
    b = sum((xs[i] - x_mean) * (closes[i] - y_mean) for i in range(n)) / \
        max(sum((xs[i] - x_mean) ** 2 for i in range(n)), 1e-10)
    a = y_mean - b * x_mean

    # Residual std for confidence interval
    residuals = [closes[i] - (a + b * xs[i]) for i in range(n)]
    res_std = math.sqrt(sum(r ** 2 for r in residuals) / n) if n > 1 else 0

    last_date = pairs[-1][0]
    last_close = closes[-1]
    forecast_points = []

    step = 0
    current = last_date
    days_added = 0
    while days_added < horizon_days:
        current = current + timedelta(days=1)
        if current.weekday() >= 5:  # skip weekends
            continue
        step += 1
        predicted = a + b * (n + step)
        predicted = max(predicted, 0.01)
        z = 1.645  # 90% confidence interval
        margin = z * res_std * math.sqrt(1 + 1 / n)
        forecast_points.append(ForecastPoint(
            date=current,
            predicted_close=round(predicted, 4),
            lower_bound=round(max(predicted - margin, 0.01), 4),
            upper_bound=round(predicted + margin, 4),
        ))
        days_added += 1

    return ForecastResponse(
        asset_id=asset_id,
        source_id=source_id,
        method="linear_regression_with_ci",
        horizon_days=horizon_days,
        last_known_close=round(last_close, 4),
        forecast=forecast_points,
    )


async def compare_assets(
    asset_ids: list[str],
    source_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> CompareResponse:
    """
    Compute pairwise Pearson correlations and individual stats for a set of assets.
    """
    series: dict[str, list[float]] = {}
    stats_list = []

    for aid in asset_ids:
        pairs = await _fetch_closes(aid, source_id, from_date, to_date)
        series[aid] = [p[1] for p in pairs]
        stats_list.append(await get_stats(aid, source_id, from_date, to_date))

    # Pearson correlation between each pair
    correlations: dict[str, float] = {}
    aids = list(asset_ids)
    for i in range(len(aids)):
        for j in range(i + 1, len(aids)):
            a, b = aids[i], aids[j]
            s_a, s_b = series[a], series[b]
            n = min(len(s_a), len(s_b))
            if n < 2:
                correlations[f"{a}:{b}"] = 0.0
                continue
            s_a = s_a[-n:]
            s_b = s_b[-n:]
            mean_a = sum(s_a) / n
            mean_b = sum(s_b) / n
            cov = sum((s_a[k] - mean_a) * (s_b[k] - mean_b) for k in range(n)) / n
            std_a = math.sqrt(sum((v - mean_a) ** 2 for v in s_a) / n) or 1e-10
            std_b = math.sqrt(sum((v - mean_b) ** 2 for v in s_b) / n) or 1e-10
            correlations[f"{a}:{b}"] = round(cov / (std_a * std_b), 4)

    return CompareResponse(
        assets=aids,
        from_date=from_date,
        to_date=to_date,
        correlations=correlations,
        stats=stats_list,
    )


async def get_export_data(
    asset_id: str,
    source_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 5000,
) -> list[dict]:
    """
    Returns flat records suitable for export to Apache Spark / pandas.
    Fields are normalised to a flat dict (no nested indicators).
    """
    col = time_series_col()
    match: dict = {"asset_id": asset_id, "source_id": source_id}
    if from_date or to_date:
        df: dict = {}
        if from_date:
            df["$gte"] = from_date
        if to_date:
            df["$lte"] = to_date
        match["series_date"] = df

    results = []
    async for doc in col.find(match, sort=[("series_date", 1)], limit=limit):
        flat = {
            "asset_id": doc.get("asset_id"),
            "source_id": doc.get("source_id"),
            "series_date": doc.get("series_date").isoformat() if doc.get("series_date") else None,
            "open": doc.get("open"),
            "high": doc.get("high"),
            "low": doc.get("low"),
            "close": doc.get("close"),
            "volume": doc.get("volume"),
        }
        # Flatten indicators into top-level fields
        for k, v in (doc.get("indicators") or {}).items():
            flat[f"ind_{k.lower()}"] = v
        results.append(flat)
    return results
