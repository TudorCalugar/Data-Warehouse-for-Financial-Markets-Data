"""
API-facing Pydantic schemas (request bodies & response models).
Separate from internal MongoDB documents.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.models.documents import AssetClass, RecordStatus, Region


# ── Shared ────────────────────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=500)


# ── Asset Schemas ─────────────────────────────────────────────────────────────

class AssetSummary(BaseModel):
    """Q1 — minimal identification info."""
    asset_id: str
    symbol: str
    asset_class: AssetClass
    description: str
    region: Region
    currency: str
    record_status: RecordStatus
    valid_from: datetime


class AssetDetail(AssetSummary):
    """Q2 — full details including extra attributes."""
    extra: dict[str, Any] = {}
    created_by: str


class AssetCreateRequest(BaseModel):
    symbol: str
    asset_class: AssetClass
    description: str
    region: Region
    currency: str = "USD"
    extra: dict[str, Any] = {}
    created_by: str = "api"


class AssetUpdateRequest(BaseModel):
    """Creates a NEW version (temporal append)."""
    description: str | None = None
    region: Region | None = None
    currency: str | None = None
    extra: dict[str, Any] | None = None


# ── Data Source Schemas ───────────────────────────────────────────────────────

class DataSourceSummary(BaseModel):
    """Q3 — minimal info."""
    source_id: str
    provider_name: str
    description: str
    record_status: RecordStatus
    valid_from: datetime


class DataSourceDetail(DataSourceSummary):
    """Q4 — full details."""
    base_url: str
    api_version: str
    supported_asset_classes: list[AssetClass]
    extra: dict[str, Any] = {}


class DataSourceCreateRequest(BaseModel):
    provider_name: str
    description: str = ""
    base_url: str = ""
    api_version: str = ""
    supported_asset_classes: list[AssetClass] = []
    extra: dict[str, Any] = {}


# ── Time Series Schemas ───────────────────────────────────────────────────────

class TimeSeriesPoint(BaseModel):
    """Single data point returned to API clients."""
    ts_id: str
    asset_id: str
    source_id: str
    series_date: datetime
    ingested_at: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    indicators: dict[str, Any]
    raw_source_ref: str


class TimeSeriesResponse(BaseModel):
    """Q5 — time series with metadata."""
    asset_id: str
    source_id: str
    from_date: datetime | None
    to_date: datetime | None
    count: int
    data: list[TimeSeriesPoint]


# ── Ingest Schemas ────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    asset_id: str
    source_id: str
    from_date: str | None = None   # ISO date string e.g. "2024-01-01"
    to_date: str | None = None


class IngestResponse(BaseModel):
    log_id: str
    asset_id: str
    source_id: str
    status: str
    records_inserted: int
    message: str


# ── Analytics Schemas ─────────────────────────────────────────────────────────

class StatsSummary(BaseModel):
    asset_id: str
    source_id: str
    from_date: datetime | None
    to_date: datetime | None
    count: int
    min_close: float | None
    max_close: float | None
    avg_close: float | None
    std_close: float | None
    total_volume: float | None
    price_change_pct: float | None    # (last - first) / first * 100


class ForecastPoint(BaseModel):
    date: datetime
    predicted_close: float
    lower_bound: float
    upper_bound: float


class ForecastResponse(BaseModel):
    asset_id: str
    source_id: str
    method: str
    horizon_days: int
    last_known_close: float | None
    forecast: list[ForecastPoint]


class CompareResponse(BaseModel):
    assets: list[str]
    from_date: datetime | None
    to_date: datetime | None
    correlations: dict[str, float]
    stats: list[StatsSummary]


# ── LLM / MCP Schemas ─────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str        # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = 1000


class ChatResponse(BaseModel):
    reply: str
    tool_calls_made: list[str] = []
