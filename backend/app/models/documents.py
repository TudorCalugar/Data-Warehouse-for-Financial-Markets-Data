"""
Domain models for the Acme Financial DWH.

Temporal DWH rules (enforced at service layer):
  - No updates or deletes in-place.
  - Each change appends a new document with a new valid_from timestamp.
  - Logical deletion adds a record with record_status = "deleted".
  - Querying for "current" state means: latest record where valid_from <= query_time
    AND record_status != "deleted".
"""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from bson import ObjectId


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enumerations ──────────────────────────────────────────────────────────────

class AssetClass(str, Enum):
    STOCK = "stock"
    BOND = "bond"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    FOREX = "forex"
    INDEX = "index"
    DERIVATIVE = "derivative"
    ETF = "etf"
    INTEREST_RATE = "interest_rate"
    OTHER = "other"


class RecordStatus(str, Enum):
    ACTIVE = "active"
    DELETED = "deleted"   # logical deletion marker


class Region(str, Enum):
    US = "US"
    EUROPE = "Europe"
    ASIA = "Asia"
    CHINA = "China"
    AFRICA = "Africa"
    LATAM = "LatAm"
    GLOBAL = "Global"
    OTHER = "Other"


# ── Asset (Financial Instrument) ──────────────────────────────────────────────

class AssetDocument(BaseModel):
    """
    Stored in MongoDB `assets` collection.
    Each "version" of an asset is a separate document (temporal append).
    """
    id: str | None = Field(None, alias="_id")          # MongoDB ObjectId as str
    asset_id: str                                        # stable logical ID across versions
    symbol: str
    asset_class: AssetClass
    description: str
    region: Region
    currency: str = "USD"
    record_status: RecordStatus = RecordStatus.ACTIVE
    valid_from: datetime = Field(default_factory=utcnow)
    # Extra heterogeneous attributes (varies per instrument class)
    extra: dict[str, Any] = Field(default_factory=dict)
    # Provenance
    created_by: str = "system"

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


# ── Data Source (Provider) ────────────────────────────────────────────────────

class DataSourceDocument(BaseModel):
    """
    Registered financial data provider.
    e.g. Nasdaq Data Link, Bloomberg, Alpha Vantage, manual upload.
    """
    id: str | None = Field(None, alias="_id")
    source_id: str                       # stable logical ID
    provider_name: str                   # "Nasdaq", "Bloomberg", …
    description: str = ""
    base_url: str = ""
    api_version: str = ""
    supported_asset_classes: list[AssetClass] = []
    record_status: RecordStatus = RecordStatus.ACTIVE
    valid_from: datetime = Field(default_factory=utcnow)
    extra: dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


# ── Time Series Data Point ────────────────────────────────────────────────────

class TimeSeriesDocument(BaseModel):
    """
    One data point in the time series for an asset from a specific source.
    Append-only — no updates or deletes.
    Heterogeneous: `indicators` holds whatever the provider sends.
    """
    id: str | None = Field(None, alias="_id")
    ts_id: str                            # unique ID for this record
    asset_id: str                         # references AssetDocument.asset_id
    source_id: str                        # references DataSourceDocument.source_id
    series_date: datetime                 # the date/time this data point represents
    ingested_at: datetime = Field(default_factory=utcnow)
    # Core cross-provider indicators (may be None if provider doesn't supply them)
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    # All other provider-specific indicators stored here
    indicators: dict[str, Any] = Field(default_factory=dict)
    # Provenance
    raw_source_ref: str = ""              # e.g. "nasdaq:EOD/GM:2024-01-15"

    class Config:
        populate_by_name = True


# ── Ingest Log ────────────────────────────────────────────────────────────────

class IngestLogDocument(BaseModel):
    id: str | None = Field(None, alias="_id")
    source_id: str
    asset_id: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    records_inserted: int = 0
    status: str = "running"          # running | success | error
    error_message: str = ""

    class Config:
        populate_by_name = True
