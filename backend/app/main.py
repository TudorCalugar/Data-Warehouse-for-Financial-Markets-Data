"""
Acme Ltd — Financial Data Warehouse
FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.db.database import connect_db, close_db
from app.api.v1.router import api_router

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    await connect_db()
    yield
    await close_db()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="""
## Acme Ltd — Financial Data Warehouse API

A temporal NoSQL data warehouse for financial market data.

### Key Features
- **UC1**: Ingest from Nasdaq Data Link & Bloomberg
- **UC2**: RESTful API for asset discovery and time-series retrieval (Q1–Q5)
- **UC3**: Analytics — statistics, forecasting, multi-asset comparison
- **UC4**: LLM assistant powered by Claude, via MCP integration

### Temporal DWH
Records are **never updated or deleted in-place**.
All changes append new versioned documents.
Use `as_of` parameter to query historical state.
        """,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow all origins for demo purposes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/", tags=["Health"])
    async def root():
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs",
        }

    @app.get("/health", tags=["Health"])
    async def health():
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
