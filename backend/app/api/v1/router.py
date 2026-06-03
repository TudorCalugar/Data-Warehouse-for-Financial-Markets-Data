from fastapi import APIRouter
from app.api.v1.endpoints import assets, sources, timeseries, ingest, analytics, assistant

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(assets.router)
api_router.include_router(sources.router)
api_router.include_router(timeseries.router)
api_router.include_router(ingest.router)
api_router.include_router(analytics.router)
api_router.include_router(assistant.router)
