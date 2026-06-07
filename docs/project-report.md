# Acme Ltd Financial DWH — Project Report

## 1. What Was Built

A fully functional financial data warehouse platform implementing all 4 use cases and all non-functional requirements from the project specification.

### Use Cases Implemented

**UC1 — Data Ingest**  
Two provider adapters: Nasdaq Data Link (real REST API with fallback to synthetic GBM data) and Bloomberg (simulated with Bloomberg-specific field names). Each ingest run is logged in `ingest_log` with provenance metadata (source_id, timestamps, record counts). The `raw_source_ref` field on every time series record traces the exact data point back to its origin.

**UC2 — REST API**  
All 5 required queries implemented:
- Q1: `GET /api/v1/assets/` — list with MongoDB aggregation picking latest version per logical asset
- Q2: `GET /api/v1/assets/{id}` — full details, with optional `as_of` parameter for point-in-time queries
- Q3: `GET /api/v1/sources/` — all providers
- Q4: `GET /api/v1/sources/{id}` — full provider details
- Q5: `GET /api/v1/timeseries/` — paginated OHLCV with date range filter

**UC3 — Analytics & Apache Spark**  
- Summary statistics (min/max/avg/std close, total volume, % change) via MongoDB aggregation
- 5-day price forecasting using linear regression on last 60 data points with 90% confidence intervals
- Multi-asset comparison: Pearson correlation matrix across assets
- Flat export endpoint (`/analytics/export`) for downstream consumption

Two standalone Apache Spark (PySpark) jobs are included in `spark/`, implementing the mandatory analytics and ML workflows:

**`spark/aggregations.py` — Spark Aggregation Workflow**
Reads all time-series records from MongoDB into a Spark DataFrame and computes: per-asset summary statistics (avg/min/max/std close, total volume), daily returns and volatility using Spark window functions, rolling 30-day average close prices, and an asset class breakdown. All results are persisted back to MongoDB (`spark_asset_summary`, `spark_volatility`, `spark_rolling_avg`, `spark_class_breakdown`).

**`spark/ml_pipeline.py` — Spark ML Pipeline**
Trains a Linear Regression model per asset × data source using Spark MLlib. Features include lag-1/2/3 close prices, rolling 5-day and 10-day averages, and a day index. The pipeline performs an 80/20 chronological train/test split, evaluates each model with RMSE and R², generates 5-day ahead forecasts, and persists all predictions and metrics to MongoDB (`spark_ml_predictions`, `spark_ml_metrics`).

**UC4 — LLM Assistant via MCP**  
Dual integration:
1. **HTTP endpoint** (`POST /assistant/chat`): Anthropic Claude with tool use, agentic loop supporting up to 5 tool-call rounds
2. **MCP Server** (`app/mcp/mcp_server.py`): stdio MCP server compatible with Claude Desktop, exposing 7 platform tools

## 2. Data Used

| Asset | Class | Providers |
|-------|-------|-----------|
| AAPL | Stock | Nasdaq (real API or synthetic), Bloomberg (simulated) |
| MSFT | Stock | Both |
| TSLA | Stock | Both |
| GM | Stock | Both |
| NFLX | Stock | Both |
| BTC | Crypto | Both |

**Data generation**: When `NASDAQ_API_KEY=demo` (default), synthetic OHLCV data is generated using geometric Brownian motion — the industry-standard model for stock price simulation. Each asset has different starting prices and volatility parameters. Bloomberg data uses different field names (`PX_BID`, `PX_ASK`, `VWAP`) demonstrating heterogeneous data handling.

Approximately **2,520 records per asset per source** (2 × 365 trading days × 2 sources), totalling ~30,000 time series points on first run.

## 3. Temporal DWH Implementation

The temporal paradigm is enforced at the service layer, not at the database level:

```python
# asset_service.py — update creates new version, never overwrites
async def update_asset(asset_id, req):
    current = await _latest_version(asset_id)
    new_doc = dict(current)
    new_doc.pop("_id", None)           # remove old MongoDB ID
    new_doc["valid_from"] = utcnow()   # new timestamp
    # apply changes to new_doc ...
    await assets_col().insert_one(new_doc)  # INSERT — never update
```

```python
# Logical delete = marker record with record_status="deleted"
async def delete_asset(asset_id):
    marker = dict(current)
    marker["record_status"] = RecordStatus.DELETED.value
    marker["valid_from"] = utcnow()
    await assets_col().insert_one(marker)   # INSERT — never delete
```

The `list_assets` query uses a MongoDB aggregation pipeline with `$group` + `$first` to efficiently retrieve only the latest version per `asset_id`.

## 4. NoSQL Design Decisions

**MongoDB** was chosen for:
- Flexible document model — heterogeneous financial instruments with different attribute sets per asset class
- No schema migration needed when Bloomberg adds new indicator fields (`indicators: {}` absorbs them)
- Native support for nested documents
- Motor driver provides async-native access from FastAPI

**Collections**:
- `assets` — financial instruments (temporal, ~1 document per change per asset)
- `data_sources` — provider registry (temporal)
- `time_series` — price data (append-only, high-volume)
- `ingest_log` — provenance and audit trail

**Indexes** on `(asset_id, valid_from DESC)` and `(asset_id, source_id, series_date DESC)` for O(log n) query performance on the hot paths.

## 5. How to Reproduce

```bash
git clone <repo>
cd acme-financial-dwh
cp .env.example .env
# Optional: add ANTHROPIC_API_KEY to .env for UC4
docker-compose up -d
# Wait ~30 seconds for seeding to complete
open http://localhost:8000/docs
```

Run tests:
```bash
pytest tests/ -v
```

Expected output: all 12 tests pass.

## 6. Known Limitations and Extensions

- Forecasting uses linear regression; production would use Prophet or ARIMA
- Bloomberg adapter simulates data; real deployment would use B-PIPE API
- No authentication on the API (suitable for academic demo)
- The React dashboard is a standalone HTML/JSX file — production would use a build pipeline
