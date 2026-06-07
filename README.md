# Acme Ltd — Financial Data Warehouse

> **Lab Project**: Data Warehouse for Financial Markets Data  
> **Stack**: Python 3.12 · FastAPI · MongoDB 7 · Motor (async) · MCP · Claude AI · Apache Spark (PySpark)  
> **Paradigm**: NoSQL Temporal DWH (append-only, no updates/deletes in-place)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Acme Financial DWH                        │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────────────────────────┐    │
│  │  UC1 Ingest │    │           UC2 REST API (FastAPI)      │    │
│  │             │    │  /assets   /sources   /timeseries     │    │
│  │  Nasdaq ────┼───▶│  /ingest   /analytics /assistant      │    │
│  │  Bloomberg  │    └──────────────┬───────────────────────┘    │
│  └─────────────┘                   │                             │
│                                    ▼                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              MongoDB 7 (NoSQL Temporal DWH)              │    │
│  │  collections: assets | data_sources | time_series |      │    │
│  │               ingest_log                                 │    │
│  │  Pattern: append-only, valid_from timestamps,            │    │
│  │           record_status="deleted" for logical deletes    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                    │                             │
│  ┌──────────────┐   ┌──────────────┴────────────────────┐       │
│  │  UC3         │   │  UC4  LLM Assistant               │       │
│  │  Analytics   │   │  MCP Server ──▶ Claude API        │       │
│  │  Stats       │   │  Tools: list_assets, get_stats,   │       │
│  │  Forecast    │   │         forecast, compare, …      │       │
│  │  Compare     │   └───────────────────────────────────┘       │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local dev / MCP server)

### 1. Clone and configure

```bash
cd acme-financial-dwh
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY for the LLM assistant
# NASDAQ_API_KEY=demo uses synthetic data (works without registration)
```

### 2. Start the stack

```bash
docker-compose up -d
# MongoDB starts, then API, then seeder runs once
```

The seeder automatically creates:
- 2 data sources (Nasdaq Data Link, Bloomberg)
- 6 assets (AAPL, MSFT, TSLA, GM, NFLX, BTC)
- ~1 year of synthetic OHLCV data per asset × source

### 3. Explore the API

```
http://localhost:8000/docs    ← Swagger UI (all endpoints)
http://localhost:8000/redoc   ← ReDoc
```

### 4. (Optional) MCP Server for Claude Desktop

```bash
# Install deps
cd backend && pip install -r requirements.txt

# Run MCP server (connects to MongoDB, exposes tools to Claude)
python -m app.mcp.mcp_server
```

Add to Claude Desktop `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "acme-financial-dwh": {
      "command": "python",
      "args": ["-m", "app.mcp.mcp_server"],
      "cwd": "/absolute/path/to/acme-financial-dwh/backend",
      "env": {
        "MONGO_URI": "mongodb://acme:acme_secret@localhost:27017/acme_dwh?authSource=admin"
      }
    }
  }
}
```

---

## API Reference (UC2 Queries)

| Query | Endpoint | Description |
|-------|----------|-------------|
| Q1 | `GET /api/v1/assets/` | List all assets (identification data) |
| Q2 | `GET /api/v1/assets/{asset_id}` | Full details of one asset |
| Q3 | `GET /api/v1/sources/` | List all data providers |
| Q4 | `GET /api/v1/sources/{source_id}` | Full details of a provider |
| Q5 | `GET /api/v1/timeseries/` | Time series data (asset + source) |

Additional endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/ingest/` | Trigger data ingest (UC1) |
| `GET /api/v1/ingest/logs` | Audit log of all ingest runs |
| `GET /api/v1/analytics/stats` | Summary statistics |
| `GET /api/v1/analytics/forecast` | Price forecast (linear regression) |
| `GET /api/v1/analytics/compare` | Multi-asset comparison + correlation |
| `GET /api/v1/analytics/export` | Flat export for Spark/pandas |
| `POST /api/v1/assistant/chat` | LLM assistant chat (UC4) |

---

## Apache Spark Workflows (UC3)

Two standalone PySpark jobs are included in the `spark/` directory, implementing the mandatory analytics and ML requirements.

### Running the Spark jobs

Prerequisites: Java 17+, PySpark (`pip install pyspark pymongo numpy`), MongoDB running (`docker-compose up -d`).

```bash
# Aggregation workflow
python spark/aggregations.py

# ML pipeline
python spark/ml_pipeline.py
```

### `spark/aggregations.py` — Aggregation Workflow

Reads time-series data from MongoDB into a Spark DataFrame and computes:

- **Per-asset summary statistics** — avg/min/max/std close price, total volume, record count
- **Daily returns & volatility** — avg daily return %, volatility (std of daily returns), best/worst single day
- **Rolling 30-day average close** — computed with a Spark window function over each asset × source partition
- **Asset class breakdown** — number of assets and average close price grouped by class (stock, crypto, etc.)

Results are persisted back to MongoDB in four collections: `spark_asset_summary`, `spark_volatility`, `spark_rolling_avg`, `spark_class_breakdown`.

### `spark/ml_pipeline.py` — ML Prediction Workflow

Trains a **Linear Regression model per asset × source** using Spark MLlib:

- **Feature engineering** — lag features (t-1, t-2, t-3 close prices), rolling 5-day and 10-day averages, day index
- **Train/test split** — 80% train / 20% test, split chronologically
- **Model training** — `pyspark.ml.regression.LinearRegression` with L2 regularisation
- **Evaluation** — RMSE and R² computed on the held-out test set
- **Forecasting** — 5-day ahead price predictions generated for each asset
- **Persistence** — predictions and model metrics saved to `spark_ml_predictions` and `spark_ml_metrics` in MongoDB

---

## Temporal DWH Design

MongoDB enforces temporal semantics at the **service layer**:

```
# "Update" AAPL description
BEFORE:  { asset_id: "asset_abc", description: "Apple Inc", valid_from: 2024-01-01 }
AFTER:   { asset_id: "asset_abc", description: "Apple Inc", valid_from: 2024-01-01 }  ← unchanged
         { asset_id: "asset_abc", description: "Apple Inc — Corrected", valid_from: 2024-06-15 }  ← new version

# "Delete" an asset
MARKER:  { asset_id: "asset_abc", record_status: "deleted", valid_from: 2024-12-01 }

# Point-in-time query
GET /api/v1/assets/asset_abc?as_of=2024-03-01  ← returns state at March 2024
```

Rules:
- Every document has `valid_from` and `record_status`
- `list_assets` uses MongoDB aggregation to return **latest non-deleted version per asset_id**
- No `UPDATE` or `DELETE` operations are used anywhere in the codebase

---

## Data Model

### `assets` collection
```json
{
  "asset_id": "asset_a1b2c3d4e5f6",
  "symbol": "AAPL",
  "asset_class": "stock",
  "description": "Apple Inc.",
  "region": "US",
  "currency": "USD",
  "record_status": "active",
  "valid_from": "2024-01-15T10:00:00Z",
  "extra": {},
  "created_by": "seeder"
}
```

### `time_series` collection
```json
{
  "ts_id": "ts_abc123",
  "asset_id": "asset_a1b2c3d4e5f6",
  "source_id": "src_x1y2z3",
  "series_date": "2024-01-15T00:00:00Z",
  "ingested_at": "2024-01-16T08:00:00Z",
  "open": 185.20, "high": 186.40, "low": 184.80, "close": 185.90,
  "volume": 62400000,
  "indicators": {
    "adj_close": 185.90,
    "split_ratio": 1.0,
    "ex_dividend": 0.0
  },
  "raw_source_ref": "nasdaq:EOD/AAPL:2024-01-15"
}
```

Heterogeneous indicators: Bloomberg records have `PX_BID`, `PX_ASK`, `VWAP`, `TURNOVER` instead of Nasdaq's `adj_close`, `split_ratio`. Both are stored in `indicators` — no schema migration needed.

---

## MCP Tools (UC4)

| Tool | Description |
|------|-------------|
| `list_assets` | Discover available instruments |
| `get_asset_detail` | Full metadata for one asset |
| `list_data_sources` | Available providers |
| `get_time_series` | OHLCV history |
| `get_stats` | Summary statistics |
| `forecast_price` | N-day price forecast |
| `compare_assets` | Correlation matrix + stats |

Example prompts for the LLM assistant:
- *"What stocks are in the warehouse?"*
- *"Show me AAPL stats for the last 90 days"*
- *"Compare AAPL and MSFT — which is less volatile?"*
- *"Forecast TSLA for the next 5 trading days"*
- *"What data providers do you have for crypto?"*

---

## Running Tests

```bash
# Start stack first
docker-compose up -d

# Install test deps
pip install pytest httpx

# Run
pytest tests/ -v
```

---

## Project Structure

```
acme-financial-dwh/
├── docker-compose.yml
├── .env.example
├── mcp-config.json            ← Claude Desktop MCP config
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            ← FastAPI app
│       ├── core/              ← config, logging
│       ├── db/                ← MongoDB connection, seeder
│       ├── models/            ← MongoDB document models
│       ├── schemas/           ← API Pydantic schemas
│       ├── services/          ← business logic (temporal DWH rules)
│       │   ├── asset_service.py
│       │   ├── datasource_service.py
│       │   ├── timeseries_service.py
│       │   ├── ingest_service.py
│       │   ├── analytics_service.py
│       │   └── llm_service.py
│       ├── data_ingest/       ← provider adapters (Nasdaq, Bloomberg)
│       ├── mcp/               ← MCP server (UC4)
│       └── api/v1/            ← REST routers
├── frontend/src/App.jsx       ← React dashboard
├── tests/test_api.py          ← integration tests
└── scripts/mongo-init.js
```
