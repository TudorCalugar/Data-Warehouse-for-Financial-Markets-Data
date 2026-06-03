"""
Demo data seeder.
Populates MongoDB with:
  - 2 data sources (Nasdaq, Bloomberg)
  - 6 assets (AAPL, MSFT, TSLA, BTC, GM, NFLX)
  - ~1 year of synthetic OHLCV data per asset × source
"""

import asyncio
from datetime import datetime, timezone
from app.db.database import connect_db, close_db
from app.services.asset_service import create_asset, list_assets
from app.services.datasource_service import create_data_source, list_data_sources
from app.services.ingest_service import run_ingest
from app.schemas.api import AssetCreateRequest, DataSourceCreateRequest, IngestRequest
from app.models.documents import AssetClass, Region
from app.core.logging import setup_logging, get_logger

setup_logging()
logger = get_logger("seeder")

ASSETS = [
    dict(symbol="AAPL", asset_class=AssetClass.STOCK, description="Apple Inc. — Consumer electronics and software", region=Region.US, currency="USD"),
    dict(symbol="MSFT", asset_class=AssetClass.STOCK, description="Microsoft Corp. — Cloud and enterprise software", region=Region.US, currency="USD"),
    dict(symbol="TSLA", asset_class=AssetClass.STOCK, description="Tesla Inc. — Electric vehicles and energy", region=Region.US, currency="USD"),
    dict(symbol="GM",   asset_class=AssetClass.STOCK, description="General Motors Co. — Automotive manufacturer", region=Region.US, currency="USD"),
    dict(symbol="NFLX", asset_class=AssetClass.STOCK, description="Netflix Inc. — Streaming media platform", region=Region.US, currency="USD"),
    dict(symbol="BTC",  asset_class=AssetClass.CRYPTO, description="Bitcoin — Decentralised digital currency", region=Region.GLOBAL, currency="USD",
         extra={"blockchain": "Bitcoin", "max_supply": 21_000_000}),
]

SOURCES = [
    dict(provider_name="Nasdaq Data Link", description="Nasdaq EOD historical data", base_url="https://data.nasdaq.com/api/v3", api_version="v3",
         supported_asset_classes=[AssetClass.STOCK, AssetClass.ETF, AssetClass.INDEX]),
    dict(provider_name="Bloomberg", description="Bloomberg market data (simulated)", base_url="https://api.bloomberg.com", api_version="blpapi",
         supported_asset_classes=[AssetClass.STOCK, AssetClass.BOND, AssetClass.CRYPTO, AssetClass.COMMODITY, AssetClass.FOREX]),
]


async def seed():
    await connect_db()
    logger.info("=== Acme DWH Seeder starting ===")

    # Check if already seeded
    existing_assets = await list_assets(limit=1)
    if existing_assets:
        logger.info("Database already seeded — skipping.")
        await close_db()
        return

    # Create data sources
    source_ids = {}
    for s in SOURCES:
        src = await create_data_source(DataSourceCreateRequest(**s))
        source_ids[s["provider_name"]] = src.source_id
        logger.info(f"Created source: {src.provider_name} → {src.source_id}")

    # Create assets
    asset_ids = {}
    for a in ASSETS:
        asset = await create_asset(AssetCreateRequest(**a))
        asset_ids[a["symbol"]] = asset.asset_id
        logger.info(f"Created asset: {a['symbol']} → {asset.asset_id}")

    # Ingest data — each asset × each compatible source
    ingest_tasks = []
    for symbol, asset_id in asset_ids.items():
        for provider_name, source_id in source_ids.items():
            ingest_tasks.append((symbol, asset_id, source_id, provider_name))

    for symbol, asset_id, source_id, provider in ingest_tasks:
        logger.info(f"Ingesting {symbol} from {provider} …")
        result = await run_ingest(IngestRequest(
            asset_id=asset_id,
            source_id=source_id,
        ))
        logger.info(f"  → {result.status}: {result.records_inserted} records")

    logger.info("=== Seeding complete ===")
    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
