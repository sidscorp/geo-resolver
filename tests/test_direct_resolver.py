import pytest
from unittest.mock import MagicMock
from shapely.geometry import box, Point

from geo_resolver.direct_resolver import DirectResolver, _score_place, _score_feature
from geo_resolver.models import Place, Feature, ResolverResult


@pytest.fixture
def direct_mock_db():
    from geo_resolver.db import PlaceDB
    db = MagicMock(spec=PlaceDB)
    db.search_places.return_value = []
    db.search_land_features.return_value = []
    db.search_water_features.return_value = []
    db.search_land_use.return_value = []
    db.search_pois.return_value = []
    return db


def test_simple_place_lookup(direct_mock_db):
    direct_mock_db.search_places.return_value = [
        Place(id="d1", name="California", subtype="region", country="US",
              region="US-CA", geometry=box(-124, 32, -114, 42),
              population=39000000, prominence=20),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("California")
    assert isinstance(result, ResolverResult)
    assert not result.geometry.is_empty


def test_poi_gets_buffered(direct_mock_db):
    direct_mock_db.search_pois.return_value = [
        Feature(id="p1", name="Eiffel Tower", source="place",
                feature_class="landmark_and_historical_building",
                geometry=Point(2.2945, 48.8584), geom_type="Point",
                is_point=True, confidence=0.95),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("Eiffel Tower")
    assert result.geometry.geom_type == "Polygon"


def test_no_results_raises(direct_mock_db):
    resolver = DirectResolver(direct_mock_db)
    with pytest.raises(RuntimeError, match="no matching"):
        resolver.resolve("Nonexistent Place")


def test_directional_modifier(direct_mock_db):
    direct_mock_db.search_places.return_value = [
        Place(id="d1", name="California", subtype="region", country="US",
              region="US-CA", geometry=box(-124, 32, -114, 42)),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("Northern California")
    assert result.geometry.bounds[1] > 36


def test_buffer_modifier(direct_mock_db):
    direct_mock_db.search_places.return_value = [
        Place(id="d1", name="Paris", subtype="locality", country="FR",
              region=None, geometry=box(2.2, 48.8, 2.4, 48.9)),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("Within 50km of Paris")
    original = box(2.2, 48.8, 2.4, 48.9)
    assert result.geometry.area > original.area


def test_prefers_higher_confidence(direct_mock_db):
    direct_mock_db.search_pois.return_value = [
        Feature(id="p1", name="Statue of Liberty", source="place",
                feature_class="landmark_and_historical_building",
                geometry=Point(-86.7, 33.5), geom_type="Point",
                is_point=True, confidence=0.64),
        Feature(id="p2", name="Statue of Liberty", source="place",
                feature_class="landmark_and_historical_building",
                geometry=Point(-74.0, 40.7), geom_type="Point",
                is_point=True, confidence=0.95),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("Statue of Liberty")
    centroid = result.geometry.centroid
    assert centroid.x < -70  # NYC area


def test_prefers_polygon_over_point(direct_mock_db):
    direct_mock_db.search_land_features.return_value = [
        Feature(id="f1", name="Ellis Island", source="land",
                feature_class="island", geometry=box(-74.04, 40.69, -74.03, 40.70),
                geom_type="Polygon"),
    ]
    direct_mock_db.search_pois.return_value = [
        Feature(id="p1", name="Ellis Island", source="place",
                feature_class="museum", geometry=Point(-74.04, 40.70),
                geom_type="Point", is_point=True, confidence=0.8),
    ]
    resolver = DirectResolver(direct_mock_db)
    result = resolver.resolve("Ellis Island")
    assert result.geometry.geom_type == "Polygon"


def test_score_place():
    p = Place(id="x", name="X", subtype="locality", country="US",
              region=None, geometry=box(0, 0, 1, 1), population=5000000, prominence=18)
    assert _score_place(p) > 10


def test_score_feature_with_wikidata():
    f = Feature(id="x", name="X", source="land", feature_class="island",
                geometry=box(0, 0, 1, 1), confidence=0.9, wikidata="Q123")
    assert _score_feature(f) > 13


def test_empty_query_raises(direct_mock_db):
    resolver = DirectResolver(direct_mock_db)
    with pytest.raises(ValueError, match="non-empty"):
        resolver.resolve("")


def test_on_step_callback(direct_mock_db):
    direct_mock_db.search_places.return_value = [
        Place(id="d1", name="Test", subtype="locality", country="US",
              region=None, geometry=box(0, 0, 1, 1)),
    ]
    steps = []
    resolver = DirectResolver(direct_mock_db)
    resolver.resolve("Test", on_step=lambda s: steps.append(s))
    assert len(steps) > 0
    assert any(s.get("type") == "search" for s in steps)
    assert any(s.get("type") == "select" for s in steps)
