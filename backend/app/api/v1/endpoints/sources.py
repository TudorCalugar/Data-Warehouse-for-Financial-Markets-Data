from fastapi import APIRouter, HTTPException, status, Query
from app.services import datasource_service
from app.schemas.api import DataSourceSummary, DataSourceDetail, DataSourceCreateRequest

router = APIRouter(prefix="/sources", tags=["Data Sources"])


@router.get("/", response_model=list[DataSourceSummary], summary="Q3 — List all data sources")
async def list_sources(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Return identification data for all registered financial data providers."""
    return await datasource_service.list_data_sources(skip=skip, limit=limit)


@router.get("/{source_id}", response_model=DataSourceDetail, summary="Q4 — Get source details")
async def get_source(source_id: str):
    """Return full details of a data source including supported asset classes."""
    src = await datasource_service.get_data_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail=f"Data source '{source_id}' not found")
    return src


@router.post("/", response_model=DataSourceDetail, status_code=status.HTTP_201_CREATED)
async def create_source(req: DataSourceCreateRequest):
    """Register a new data provider."""
    return await datasource_service.create_data_source(req)
