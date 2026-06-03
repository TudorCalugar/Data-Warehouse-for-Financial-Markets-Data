"""
UC4 — LLM Assistant Service.
Integrates with Anthropic Claude via the API.
The assistant can use platform tools (list_assets, get_stats, etc.)
to answer questions grounded in the DWH data.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone

import anthropic

from app.core.config import get_settings
from app.services.asset_service import list_assets, get_asset_detail
from app.services.datasource_service import list_data_sources
from app.services.timeseries_service import get_time_series
from app.services.analytics_service import get_stats, forecast_price, compare_assets
from app.schemas.api import ChatRequest, ChatResponse
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the Acme Ltd Financial Data Assistant — a helpful, data-grounded analyst.
You have access to tools that query a live financial data warehouse containing stocks, crypto, bonds, and more.
Always use the tools to fetch real data before answering. Never invent figures or prices.
When summarising statistics, explain them in plain English and highlight key insights.
If asked to compare assets, fetch data for each, then explain the correlation and relative performance.
Keep answers concise but actionable."""

TOOLS: list[dict] = [
    {
        "name": "list_assets",
        "description": "List all financial assets in the warehouse. Filter by asset_class if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_class": {"type": "string", "description": "e.g. stock, crypto, bond, commodity"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "get_asset_detail",
        "description": "Get full metadata for a specific asset by asset_id.",
        "input_schema": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
        },
    },
    {
        "name": "list_data_sources",
        "description": "List all registered data providers (Nasdaq, Bloomberg, etc.)",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_time_series",
        "description": "Retrieve recent OHLCV price data for an asset from a data source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "source_id": {"type": "string"},
                "from_date": {"type": "string", "description": "ISO date e.g. 2024-01-01"},
                "to_date": {"type": "string"},
                "limit": {"type": "integer", "default": 15},
            },
            "required": ["asset_id", "source_id"],
        },
    },
    {
        "name": "get_stats",
        "description": "Get summary statistics: min/max/avg close, std deviation, price change %, total volume.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "source_id": {"type": "string"},
                "from_date": {"type": "string"},
                "to_date": {"type": "string"},
            },
            "required": ["asset_id", "source_id"],
        },
    },
    {
        "name": "forecast_price",
        "description": "Forecast next N trading days close price using linear trend regression.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "source_id": {"type": "string"},
                "horizon_days": {"type": "integer", "default": 5},
            },
            "required": ["asset_id", "source_id"],
        },
    },
    {
        "name": "compare_assets",
        "description": "Compare multiple assets: Pearson correlation and individual stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_ids": {"type": "array", "items": {"type": "string"}},
                "source_id": {"type": "string"},
                "from_date": {"type": "string"},
                "to_date": {"type": "string"},
            },
            "required": ["asset_ids", "source_id"],
        },
    },
]


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


async def _execute_tool(name: str, inp: dict) -> str:
    """Execute a platform tool call and return JSON string result."""
    try:
        if name == "list_assets":
            result = await list_assets(limit=inp.get("limit", 10), asset_class=inp.get("asset_class"))
            return json.dumps([r.model_dump() for r in result], default=str)

        elif name == "get_asset_detail":
            r = await get_asset_detail(inp["asset_id"])
            return json.dumps(r.model_dump() if r else {"error": "Not found"}, default=str)

        elif name == "list_data_sources":
            result = await list_data_sources()
            return json.dumps([r.model_dump() for r in result], default=str)

        elif name == "get_time_series":
            r = await get_time_series(
                asset_id=inp["asset_id"],
                source_id=inp["source_id"],
                from_date=_parse_dt(inp.get("from_date")),
                to_date=_parse_dt(inp.get("to_date")),
                limit=inp.get("limit", 15),
            )
            return json.dumps(r.model_dump(), default=str)

        elif name == "get_stats":
            r = await get_stats(
                asset_id=inp["asset_id"],
                source_id=inp["source_id"],
                from_date=_parse_dt(inp.get("from_date")),
                to_date=_parse_dt(inp.get("to_date")),
            )
            return json.dumps(r.model_dump(), default=str)

        elif name == "forecast_price":
            r = await forecast_price(
                asset_id=inp["asset_id"],
                source_id=inp["source_id"],
                horizon_days=inp.get("horizon_days", 5),
            )
            return json.dumps(r.model_dump(), default=str)

        elif name == "compare_assets":
            r = await compare_assets(
                asset_ids=inp["asset_ids"],
                source_id=inp["source_id"],
                from_date=_parse_dt(inp.get("from_date")),
                to_date=_parse_dt(inp.get("to_date")),
            )
            return json.dumps(r.model_dump(), default=str)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        logger.exception(f"Tool execution error: {name}")
        return json.dumps({"error": str(e)})


async def chat(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return ChatResponse(
            reply="LLM assistant is not configured. Set ANTHROPIC_API_KEY in .env to enable it.",
            tool_calls_made=[],
        )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    tool_calls_made: list[str] = []

    # Agentic loop — allow up to 5 tool call rounds
    for _ in range(5):
        response = await client.messages.create(
            model=settings.llm_model,
            max_tokens=req.max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return ChatResponse(reply=text, tool_calls_made=tool_calls_made)

        if response.stop_reason == "tool_use":
            # Append assistant's message with tool use blocks
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_made.append(block.name)
                    result_str = await _execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    # Fallback: extract any text from last response
    text = " ".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    return ChatResponse(reply=text or "No response generated.", tool_calls_made=tool_calls_made)
