"""
UC1 — Data Ingest from Nasdaq Data Link (EOD dataset).
Uses the public REST API: https://data.nasdaq.com/api/v3/datasets/
Falls back to synthetic demo data when api_key == "demo" or rate-limited.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
import random
import math

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

NASDAQ_EOD_URL = "https://data.nasdaq.com/api/v3/datasets/EOD/{symbol}.json"

# Column order returned by Nasdaq EOD dataset
NASDAQ_COLUMNS = ["Open", "High", "Low", "Close", "Volume",
                  "Ex-Dividend", "Split Ratio",
                  "Adj. Open", "Adj. High", "Adj. Low", "Adj. Close", "Adj. Volume"]


async def fetch_nasdaq_timeseries(
    symbol: str,
    asset_id: str,
    source_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """
    Fetch EOD time series from Nasdaq Data Link for a given symbol.
    Returns list of dicts ready for insert_time_series_batch().
    """
    settings = get_settings()

    if settings.nasdaq_api_key == "demo":
        logger.warning(f"Using synthetic demo data for {symbol} (no Nasdaq API key)")
        return _generate_synthetic_data(symbol, asset_id, source_id, from_date, to_date)

    params: dict[str, Any] = {"api_key": settings.nasdaq_api_key}
    if from_date:
        params["start_date"] = from_date
    if to_date:
        params["end_date"] = to_date

    url = NASDAQ_EOD_URL.format(symbol=symbol.upper())
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 429, 422):
            logger.warning(f"Nasdaq API error {e.response.status_code} — falling back to synthetic data")
            return _generate_synthetic_data(symbol, asset_id, source_id, from_date, to_date)
        raise

    dataset = payload.get("dataset", {})
    column_names = dataset.get("column_names", NASDAQ_COLUMNS)
    raw_data = dataset.get("data", [])

    records = []
    for row in raw_data:
        row_dict = dict(zip(column_names, row))
        date_str = row_dict.get("Date") or row_dict.get("date")
        if not date_str:
            continue
        series_date = datetime.fromisoformat(str(date_str)).replace(tzinfo=timezone.utc)

        record = {
            "ts_id": f"ts_{uuid.uuid4().hex[:16]}",
            "asset_id": asset_id,
            "source_id": source_id,
            "series_date": series_date,
            "ingested_at": datetime.now(timezone.utc),
            "open": _safe_float(row_dict.get("Open")),
            "high": _safe_float(row_dict.get("High")),
            "low": _safe_float(row_dict.get("Low")),
            "close": _safe_float(row_dict.get("Close")),
            "volume": _safe_float(row_dict.get("Volume")),
            "indicators": {
                k: v for k, v in row_dict.items()
                if k not in ("Date", "Open", "High", "Low", "Close", "Volume")
                and v is not None
            },
            "raw_source_ref": f"nasdaq:EOD/{symbol}:{date_str}",
        }
        records.append(record)

    logger.info(f"Fetched {len(records)} records from Nasdaq for {symbol}")
    return records


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _generate_synthetic_data(
    symbol: str,
    asset_id: str,
    source_id: str,
    from_date: str | None,
    to_date: str | None,
    days: int = 365,
) -> list[dict]:
    """
    Generate realistic synthetic OHLCV data using geometric Brownian motion.
    Used when no real API key is available.
    """
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    if from_date:
        start = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
    if to_date:
        end = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)

    # Seed based on symbol for reproducibility
    rng = random.Random(hash(symbol) % (2**32))

    # Starting prices vary by symbol
    base_prices = {
        "AAPL": 175.0, "MSFT": 380.0, "GOOGL": 140.0,
        "AMZN": 185.0, "TSLA": 250.0, "BTC": 45000.0,
        "GM": 35.0, "NFLX": 600.0, "NVDA": 800.0,
    }
    price = base_prices.get(symbol.upper(), 100.0 + rng.uniform(-50, 200))

    records = []
    current = start
    dt = 1 / 252  # daily time step
    mu = 0.0008   # daily drift
    sigma = 0.018  # daily volatility

    while current <= end:
        # Skip weekends
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        # GBM step
        z = rng.gauss(0, 1)
        price *= math.exp((mu - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * z)
        price = max(price, 0.01)

        spread = price * rng.uniform(0.005, 0.025)
        open_p = price + rng.uniform(-spread / 2, spread / 2)
        high_p = max(open_p, price) + rng.uniform(0, spread)
        low_p = min(open_p, price) - rng.uniform(0, spread)
        volume = rng.uniform(1_000_000, 50_000_000)

        record = {
            "ts_id": f"ts_{uuid.uuid4().hex[:16]}",
            "asset_id": asset_id,
            "source_id": source_id,
            "series_date": current,
            "ingested_at": datetime.now(timezone.utc),
            "open": round(open_p, 4),
            "high": round(high_p, 4),
            "low": round(low_p, 4),
            "close": round(price, 4),
            "volume": round(volume, 0),
            "indicators": {
                "adj_close": round(price, 4),
                "adj_volume": round(volume, 0),
                "split_ratio": 1.0,
                "ex_dividend": 0.0,
            },
            "raw_source_ref": f"synthetic:{symbol}:{current.date()}",
        }
        records.append(record)
        current += timedelta(days=1)

    logger.info(f"Generated {len(records)} synthetic records for {symbol}")
    return records
