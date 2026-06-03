"""
Integration tests for Acme Financial DWH API.
Run with: pytest tests/ -v
Requires the full stack to be running (docker-compose up).
"""

import pytest
import httpx

BASE = "http://localhost:8000/api/v1"


@pytest.fixture(scope="session")
def client():
    return httpx.Client(base_url=BASE, timeout=30)


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health", base_url="http://localhost:8000")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Data Sources (Q3, Q4) ─────────────────────────────────────────────────────

def test_list_sources(client):
    r = client.get("/sources/")
    assert r.status_code == 200
    sources = r.json()
    assert isinstance(sources, list)
    assert len(sources) >= 1
    s = sources[0]
    assert "source_id" in s
    assert "provider_name" in s


def test_get_source_detail(client):
    r = client.get("/sources/")
    sources = r.json()
    if not sources:
        pytest.skip("No sources seeded")
    source_id = sources[0]["source_id"]
    r2 = client.get(f"/sources/{source_id}")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["source_id"] == source_id
    assert "base_url" in detail


# ── Assets (Q1, Q2) ───────────────────────────────────────────────────────────

def test_list_assets(client):
    r = client.get("/assets/")
    assert r.status_code == 200
    assets = r.json()
    assert isinstance(assets, list)
    assert len(assets) >= 1
    a = assets[0]
    assert "asset_id" in a
    assert "symbol" in a
    assert "asset_class" in a


def test_create_and_get_asset(client):
    # Create
    payload = {
        "symbol": "TEST",
        "asset_class": "stock",
        "description": "Test asset for pytest",
        "region": "US",
        "currency": "USD",
    }
    r = client.post("/assets/", json=payload)
    assert r.status_code == 201
    created = r.json()
    asset_id = created["asset_id"]
    assert created["symbol"] == "TEST"

    # Q2 — Get detail
    r2 = client.get(f"/assets/{asset_id}")
    assert r2.status_code == 200
    assert r2.json()["asset_id"] == asset_id


def test_temporal_update(client):
    """Verify that update creates a new version, not overwrite."""
    r = client.post("/assets/", json={
        "symbol": "TEMPTEST", "asset_class": "stock",
        "description": "Version 1", "region": "US",
    })
    assert r.status_code == 201
    asset_id = r.json()["asset_id"]

    # Update
    r2 = client.patch(f"/assets/{asset_id}", json={"description": "Version 2"})
    assert r2.status_code == 200
    assert r2.json()["description"] == "Version 2"

    # History should have 2 versions
    r3 = client.get(f"/assets/{asset_id}/history")
    assert r3.status_code == 200
    history = r3.json()
    assert len(history) >= 2
    descriptions = [v["description"] for v in history]
    assert "Version 1" in descriptions
    assert "Version 2" in descriptions


def test_temporal_delete(client):
    """Verify deletion is a marker, not a physical removal."""
    r = client.post("/assets/", json={
        "symbol": "DELTEST", "asset_class": "stock",
        "description": "To be deleted", "region": "US",
    })
    asset_id = r.json()["asset_id"]

    # Delete
    r2 = client.delete(f"/assets/{asset_id}")
    assert r2.status_code == 204

    # History still contains the deletion marker
    r3 = client.get(f"/assets/{asset_id}/history")
    history = r3.json()
    statuses = [v["record_status"] for v in history]
    assert "deleted" in statuses


# ── Time Series (Q5) ──────────────────────────────────────────────────────────

def test_time_series(client):
    assets = client.get("/assets/").json()
    sources = client.get("/sources/").json()
    if not assets or not sources:
        pytest.skip("No data seeded")

    asset_id = assets[0]["asset_id"]
    source_id = sources[0]["source_id"]

    r = client.get(f"/timeseries/?asset_id={asset_id}&source_id={source_id}&limit=10")
    if r.status_code == 404:
        pytest.skip("No time series data for this asset/source combo")
    assert r.status_code == 200
    ts = r.json()
    assert ts["asset_id"] == asset_id
    assert ts["source_id"] == source_id
    assert ts["count"] > 0
    assert len(ts["data"]) > 0
    # Each point has close price
    point = ts["data"][0]
    assert "close" in point
    assert "series_date" in point


# ── Analytics (UC3) ───────────────────────────────────────────────────────────

def test_analytics_stats(client):
    assets = client.get("/assets/").json()
    sources = client.get("/sources/").json()
    if not assets or not sources:
        pytest.skip("No data seeded")

    asset_id = assets[0]["asset_id"]
    source_id = sources[0]["source_id"]
    r = client.get(f"/analytics/stats?asset_id={asset_id}&source_id={source_id}")
    assert r.status_code == 200
    stats = r.json()
    assert "avg_close" in stats
    assert "min_close" in stats
    assert "max_close" in stats


def test_forecast(client):
    assets = client.get("/assets/").json()
    sources = client.get("/sources/").json()
    if not assets or not sources:
        pytest.skip("No data")

    asset_id = assets[0]["asset_id"]
    source_id = sources[0]["source_id"]
    r = client.get(f"/analytics/forecast?asset_id={asset_id}&source_id={source_id}&horizon_days=3")
    assert r.status_code == 200
    fc = r.json()
    assert fc["horizon_days"] == 3
    assert len(fc["forecast"]) == 3
    assert "predicted_close" in fc["forecast"][0]


# ── Ingest (UC1) ──────────────────────────────────────────────────────────────

def test_ingest_log(client):
    r = client.get("/ingest/logs?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
