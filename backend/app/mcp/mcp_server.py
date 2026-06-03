"""
UC4 — MCP Server for Acme Financial DWH.
Exposes platform capabilities as MCP tools so any MCP-compatible LLM
(Claude, GPT-4o, etc.) can call them via the Model Context Protocol.

Tools exposed:
  - list_assets          : discover available financial assets
  - get_asset_detail     : full metadata for one asset
  - list_data_sources    : available data providers
  - get_time_series      : OHLCV data for asset + source
  - get_stats            : summary statistics
  - forecast_price       : next-N-days price forecast
  - compare_assets       : side-by-side correlation + stats
  - search_assets        : filter assets by class, region, symbol substring
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from app.db.database import connect_db
from app.services.asset_service import list_assets, get_asset_detail
from app.services.datasource_service import list_data_sources, get_data_source
from app.services.timeseries_service import get_time_series
from app.services.analytics_service import get_stats, forecast_price, compare_assets
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

server = Server("acme-financial-dwh")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_assets",
            description="List all financial assets (instruments) available in the data warehouse. Returns asset_id, symbol, class, description, region.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_class": {"type": "string", "description": "Filter by class: stock, bond, crypto, commodity, forex, index, etf, other"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        types.Tool(
            name="get_asset_detail",
            description="Get full metadata for a specific asset by its asset_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "The asset_id (e.g. asset_abc123)"},
                },
                "required": ["asset_id"],
            },
        ),
        types.Tool(
            name="list_data_sources",
            description="List all data providers (sources) available: Nasdaq, Bloomberg, etc.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_time_series",
            description="Retrieve historical OHLCV price data for an asset from a specific data source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "from_date": {"type": "string", "description": "ISO date, e.g. 2024-01-01"},
                    "to_date": {"type": "string", "description": "ISO date, e.g. 2024-12-31"},
                    "limit": {"type": "integer", "default": 30},
                },
                "required": ["asset_id", "source_id"],
            },
        ),
        types.Tool(
            name="get_stats",
            description="Get summary statistics for an asset: min/max/avg close, std deviation, total volume, price change %.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                },
                "required": ["asset_id", "source_id"],
            },
        ),
        types.Tool(
            name="forecast_price",
            description="Forecast the next N trading days close price for an asset using linear trend regression.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "horizon_days": {"type": "integer", "default": 5, "description": "Number of trading days to forecast"},
                },
                "required": ["asset_id", "source_id"],
            },
        ),
        types.Tool(
            name="compare_assets",
            description="Compare multiple assets: correlation matrix and individual stats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_ids": {"type": "array", "items": {"type": "string"}, "description": "List of asset_ids to compare"},
                    "source_id": {"type": "string"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                },
                "required": ["asset_ids", "source_id"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    await connect_db()
    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, default=str, indent=2))]
    except Exception as e:
        logger.exception(f"MCP tool error: {name}")
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def _dispatch(name: str, args: dict):
    def _parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    if name == "list_assets":
        assets = await list_assets(limit=args.get("limit", 20), asset_class=args.get("asset_class"))
        return [a.model_dump() for a in assets]

    elif name == "get_asset_detail":
        asset = await get_asset_detail(args["asset_id"])
        return asset.model_dump() if asset else {"error": "Asset not found"}

    elif name == "list_data_sources":
        sources = await list_data_sources()
        return [s.model_dump() for s in sources]

    elif name == "get_time_series":
        ts = await get_time_series(
            asset_id=args["asset_id"],
            source_id=args["source_id"],
            from_date=_parse_dt(args.get("from_date")),
            to_date=_parse_dt(args.get("to_date")),
            limit=args.get("limit", 30),
        )
        return ts.model_dump()

    elif name == "get_stats":
        stats = await get_stats(
            asset_id=args["asset_id"],
            source_id=args["source_id"],
            from_date=_parse_dt(args.get("from_date")),
            to_date=_parse_dt(args.get("to_date")),
        )
        return stats.model_dump()

    elif name == "forecast_price":
        fc = await forecast_price(
            asset_id=args["asset_id"],
            source_id=args["source_id"],
            horizon_days=args.get("horizon_days", 5),
        )
        return fc.model_dump()

    elif name == "compare_assets":
        comp = await compare_assets(
            asset_ids=args["asset_ids"],
            source_id=args["source_id"],
            from_date=_parse_dt(args.get("from_date")),
            to_date=_parse_dt(args.get("to_date")),
        )
        return comp.model_dump()

    else:
        return {"error": f"Unknown tool: {name}"}


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
