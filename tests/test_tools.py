import json

import pytest
from shapely.geometry import box

from geo_resolver.tools import ToolExecutor, POI_BUFFER_KM


def test_search_places(mock_db):
    ex = ToolExecutor(mock_db)
    raw = ex.execute("search_places", {"name": "TestPlace"})
    results = json.loads(raw)
    assert len(results) == 1
    assert "geometry_id" in results[0]
    assert results[0]["geometry_id"] == "g1"


def test_search_places_no_geometry(mock_db):
    from geo_resolver.models import Place

    mock_db.search_places.return_value = [
        Place(id="x", name="NoGeom", subtype="locality", country=None, region=None, geometry=None)
    ]
    ex = ToolExecutor(mock_db)
    raw = ex.execute("search_places", {"name": "NoGeom"})
    results = json.loads(raw)
    assert "geometry_id" not in results[0]
    assert results[0]["has_geometry"] is False


def test_search_pois_suggested_buffer(mock_db):
    ex = ToolExecutor(mock_db)
    raw = ex.execute("search_pois", {"name": "TestPOI"})
    results = json.loads(raw)
    assert results[0]["suggested_buffer_km"] == POI_BUFFER_KM["museum"]


def test_union_op(mock_db):
    ex = ToolExecutor(mock_db)
    ex.execute("search_places", {"name": "A"})  # g1
    # Add a second geometry manually
    ex.geometries["g2"] = box(1, 1, 2, 2)
    ex._counter = 2
    raw = ex.execute("union", {"geometry_ids": ["g1", "g2"]})
    result = json.loads(raw)
    assert "geometry_id" in result
    assert result["geometry_id"] == "g3"


def test_intersection_op(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex.geometries["g2"] = box(0.5, 0.5, 1.5, 1.5)
    ex._counter = 2
    raw = ex.execute("intersection", {"geometry_id_a": "g1", "geometry_id_b": "g2"})
    result = json.loads(raw)
    assert result["geometry_id"] == "g3"


def test_difference_op(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex.geometries["g2"] = box(0.5, 0.5, 1.5, 1.5)
    ex._counter = 2
    raw = ex.execute("difference", {"geometry_id_a": "g1", "geometry_id_b": "g2"})
    result = json.loads(raw)
    assert result["geometry_id"] == "g3"


def test_buffer_op(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex._counter = 1
    raw = ex.execute("buffer", {"geometry_id": "g1", "distance_km": 10})
    result = json.loads(raw)
    assert result["geometry_id"] == "g2"
    assert ex.geometries["g2"].contains(ex.geometries["g1"])


def test_directional_subset_op(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 2, 2)
    ex._counter = 1
    raw = ex.execute("directional_subset", {"geometry_id": "g1", "direction": "north"})
    result = json.loads(raw)
    assert result["geometry_id"] == "g2"


def test_finalize(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex._counter = 1
    raw = ex.execute("finalize", {"geometry_id": "g1"})
    result = json.loads(raw)
    assert result["status"] == "finalized"
    assert ex.final_id == "g1"


def test_unknown_geometry_id(mock_db):
    ex = ToolExecutor(mock_db)
    raw = ex.execute("finalize", {"geometry_id": "g999"})
    result = json.loads(raw)
    assert "error" in result


def test_intersection_empty_warning(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex.geometries["g2"] = box(5, 5, 6, 6)  # disjoint
    ex._counter = 2
    raw = ex.execute("intersection", {"geometry_id_a": "g1", "geometry_id_b": "g2"})
    result = json.loads(raw)
    assert result["warning"] == "result geometry is empty"


def test_difference_empty_warning(mock_db):
    ex = ToolExecutor(mock_db)
    ex.geometries["g1"] = box(0, 0, 1, 1)
    ex.geometries["g2"] = box(0, 0, 1, 1)  # identical
    ex._counter = 2
    raw = ex.execute("difference", {"geometry_id_a": "g1", "geometry_id_b": "g2"})
    result = json.loads(raw)
    assert result["warning"] == "result geometry is empty"


def test_unknown_tool(mock_db):
    ex = ToolExecutor(mock_db)
    raw = ex.execute("nonexistent_tool", {})
    result = json.loads(raw)
    assert "error" in result
    assert "Unknown tool" in result["error"]
