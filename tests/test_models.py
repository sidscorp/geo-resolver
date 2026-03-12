import json

from shapely.geometry import Point, box

from geo_resolver.models import Place, Feature, ResolverResult, TokenUsage


def test_place_to_dict_with_geometry(mock_place):
    d = mock_place.to_dict()
    assert d["has_geometry"] is True
    assert d["name"] == "TestPlace"
    assert "geometry" not in d


def test_place_to_dict_without_geometry():
    p = Place(id="x", name="NoGeom", subtype="locality", country=None, region=None, geometry=None)
    d = p.to_dict()
    assert d["has_geometry"] is False


def test_feature_to_dict(mock_feature):
    d = mock_feature.to_dict()
    assert d["has_geometry"] is True
    assert d["source"] == "water"
    assert d["geom_type"] == "Polygon"
    assert d["is_point"] is False


def test_feature_to_dict_point():
    f = Feature(
        id="p1", name="Spot", source="place", feature_class="museum",
        geometry=Point(1, 2), geom_type="Point", is_point=True,
    )
    d = f.to_dict()
    assert d["is_point"] is True
    assert d["geom_type"] == "Point"


def test_resolver_result_geojson():
    geom = box(0, 0, 1, 1)
    r = ResolverResult(query="test", geometry=geom)
    gj = r.geojson
    assert gj["type"] == "Feature"
    assert gj["properties"]["query"] == "test"
    assert gj["geometry"]["type"] == "Polygon"


def test_resolver_result_bounds():
    geom = box(10, 20, 30, 40)
    r = ResolverResult(query="bounds test", geometry=geom)
    assert r.bounds == (10.0, 20.0, 30.0, 40.0)


def test_resolver_result_area_km2():
    geom = box(0, 0, 1, 1)
    r = ResolverResult(query="area test", geometry=geom)
    area = r.area_km2
    assert isinstance(area, float)
    assert area > 0


def test_token_usage_defaults():
    usage = TokenUsage()
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0


def test_resolver_result_save(tmp_path):
    geom = box(0, 0, 1, 1)
    r = ResolverResult(query="save test", geometry=geom)
    path = tmp_path / "out.geojson"
    r.save(str(path))
    data = json.loads(path.read_text())
    assert data["type"] == "Feature"
    assert data["properties"]["query"] == "save test"
