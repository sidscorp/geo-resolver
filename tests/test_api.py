import json
from unittest.mock import patch, MagicMock

import pytest
from shapely.geometry import box

from geo_resolver.models import ResolverResult


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from geo_resolver.api.main import app

    return TestClient(app)


@pytest.fixture
def mock_resolver():
    resolver = MagicMock()
    geom = box(0, 0, 1, 1)
    resolver.resolve.return_value = ResolverResult(
        query="test query",
        geometry=geom,
        steps=[{"tool": "search_places", "message": "Searching..."}],
    )
    return resolver


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_resolve(client, mock_resolver):
    with patch("geo_resolver.api.routes.get_resolver", return_value=mock_resolver):
        resp = client.post("/api/resolve", json={"query": "test query"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"
    assert data["geojson"]["type"] == "Feature"
    assert data["area_km2"] > 0
    assert isinstance(data["bounds"], list)
    assert len(data["bounds"]) == 4


def test_resolve_empty_query(client):
    resp = client.post("/api/resolve", json={"query": ""})
    assert resp.status_code == 422


def test_resolve_500_hides_exception_details(client):
    bad_resolver = MagicMock()
    bad_resolver.resolve.side_effect = RuntimeError("secret database credentials xyz")

    with patch("geo_resolver.api.routes.get_resolver", return_value=bad_resolver):
        resp = client.post("/api/resolve", json={"query": "test query"})
    assert resp.status_code == 500
    assert "secret" not in resp.text
    assert "Internal server error" in resp.json()["detail"]


def test_resolve_stream(client, mock_resolver):
    with patch("geo_resolver.api.routes.get_resolver", return_value=mock_resolver):
        resp = client.post("/api/resolve/stream", json={"query": "test query"})
    assert resp.status_code == 200
    # SSE response should contain event data
    text = resp.text
    assert "event:" in text or "data:" in text
