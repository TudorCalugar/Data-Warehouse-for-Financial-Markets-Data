"""
Bloomberg-style adapter.
Bloomberg's real API is enterprise-only, so we simulate realistic data
with Bloomberg-specific field names (BID, ASK, LAST_PRICE, etc.)
In a real deployment, replace _generate_bloomberg_data() with actual
Bloomberg B-PIPE / BQuant API calls.
"""

from __future__ import annotations
import uuid
import math
import random
from datetime import datetime, timezone, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


async def fetch_bloomberg_timeseries(
    symbol: str,
    asset_id: str,
    source_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """
    Fetch (or simulate) Bloomberg time series data.
    Bloomberg provides different indicators than Nasdaq (BID/ASK spread, etc.)
    """
    logger.info(f"Bloomberg adapter: generating data for {symbol} (simulation)")
    return _generate_bloomberg_data(symbol, asset_id, source_id, from_date, to_date)


def _generate_bloomberg_data(
    symbol: str,
    asset_id: str,
    source_id: str,
    from_date: str | None,
    to_date: str | None,
    days: int = 180,
) -> list[dict]:
    """
    Simulate Bloomberg EOD with their characteristic field set:
    PX_LAST, PX_BID, PX_ASK, PX_VOLUME, VWAP, TURNOVER, QUOTED_VALUE
    Note: different field names than Nasdaq — demonstrates heterogeneous data.
    """
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    if from_date:
        start = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
    if to_date:
        end = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)

    rng = random.Random((hash(symbol) + 42) % (2**32))
    base_prices = {
        "AAPL": 175.0, "MSFT": 380.0, "GOOGL": 140.0,
        "AMZN": 185.0, "TSLA": 250.0, "BTC": 45000.0,
        "GM": 35.0, "NFLX": 600.0, "NVDA": 800.0,
    }
    price = base_prices.get(symbol.upper(), 100.0 + rng.uniform(-50, 200))
    mu = 0.0008
    sigma = 0.020

    records = []
    current = start
    dt = 1 / 252

    while current <= end:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        z = rng.gauss(0, 1)
        price *= math.exp((mu - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * z)
        price = max(price, 0.01)

        spread = price * rng.uniform(0.001, 0.005)
        bid = price - spread / 2
        ask = price + spread / 2
        volume = rng.uniform(800_000, 40_000_000)
        vwap = price * rng.uniform(0.998, 1.002)
        turnover = volume * vwap

        record = {
            "ts_id": f"ts_{uuid.uuid4().hex[:16]}",
            "asset_id": asset_id,
            "source_id": source_id,
            "series_date": current,
            "ingested_at": datetime.now(timezone.utc),
            # Map Bloomberg field names to common fields
            "open": None,          # Bloomberg EOD often omits open
            "high": None,          # Same
            "low": None,
            "close": round(price, 4),   # PX_LAST → close
            "volume": round(volume, 0),  # PX_VOLUME → volume
            # Bloomberg-specific extras — stored in indicators
            "indicators": {
                "PX_LAST": round(price, 4),
                "PX_BID": round(bid, 4),
                "PX_ASK": round(ask, 4),
                "PX_VOLUME": round(volume, 0),
                "VWAP": round(vwap, 4),
                "TURNOVER": round(turnover, 2),
                "BID_ASK_SPREAD": round(spread, 6),
                "QUOTED_VALUE": round(price, 4),
            },
            "raw_source_ref": f"bloomberg:{symbol}:{current.date()}",
        }
        records.append(record)
        current += timedelta(days=1)

    logger.info(f"Generated {len(records)} Bloomberg-style records for {symbol}")
    return records
