"""Integration tests for PlaceDB against real (tiny) DuckDB databases."""

import duckdb
import pytest
from shapely.geometry import box, Point
from shapely import wkb

from geo_resolver.db import PlaceDB


@pytest.fixture
def tmp_db(tmp_path):
    """Build minimal DuckDB databases that mirror the real schema."""
    # --- divisions.duckdb ---
    div_path = tmp_path / "divisions.duckdb"
    con = duckdb.connect(str(div_path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("""
        CREATE TABLE divisions (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            subtype VARCHAR, country VARCHAR, region VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO divisions VALUES
            ('d1', 'California',    NULL,            'region',   'US', 'US-CA'),
            ('d2', 'Georgia',       NULL,            'region',   'US', 'US-GA'),
            ('d3', 'Georgia',       'Georgia',       'country',  'GE', NULL),
            ('d4', 'Oakland',       NULL,            'locality', 'US', 'US-CA'),
            ('d5', 'San Francisco', 'San Francisco', 'locality', 'US', 'US-CA')
    """)

    # division_areas — WKB blobs for d1 and d5
    ca_wkb = wkb.dumps(box(-124, 32, -114, 42))
    sf_wkb = wkb.dumps(box(-122.52, 37.70, -122.35, 37.82))

    con.execute("CREATE TABLE division_areas (division_id VARCHAR, geom_wkb BLOB)")
    con.execute(
        "INSERT INTO division_areas VALUES ($1, $2), ($3, $4)",
        ["d1", ca_wkb, "d5", sf_wkb],
    )
    con.close()

    # --- features.duckdb ---
    feat_path = tmp_path / "features.duckdb"
    con = duckdb.connect(str(feat_path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("""
        CREATE TABLE land_features (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            class VARCHAR, geom_wkb BLOB, geom_type VARCHAR
        )
    """)
    mt_wkb = wkb.dumps(Point(-121.9, 36.6))
    con.execute(
        "INSERT INTO land_features VALUES ($1, $2, $3, $4, $5, $6)",
        ["lf1", "Mount Diablo", "Mount Diablo", "peak", mt_wkb, "Point"],
    )

    con.execute("""
        CREATE TABLE water_features (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            class VARCHAR, geom_wkb BLOB, geom_type VARCHAR
        )
    """)
    lake_wkb = wkb.dumps(box(-122.5, 37.9, -122.4, 38.0))
    con.execute(
        "INSERT INTO water_features VALUES ($1, $2, $3, $4, $5, $6)",
        ["wf1", "Lake Merritt", "Lake Merritt", "lake", lake_wkb, "Polygon"],
    )

    con.execute("""
        CREATE TABLE land_use_features (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            subtype VARCHAR, class VARCHAR, geom_wkb BLOB, geom_type VARCHAR
        )
    """)
    park_wkb = wkb.dumps(box(-122.5, 37.75, -122.45, 37.78))
    con.execute(
        "INSERT INTO land_use_features VALUES ($1, $2, $3, $4, $5, $6, $7)",
        ["lu1", "Golden Gate Park", "Golden Gate Park", "park", "park", park_wkb, "Polygon"],
    )
    con.close()

    # --- places.duckdb ---
    places_path = tmp_path / "places.duckdb"
    con = duckdb.connect(str(places_path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("""
        CREATE TABLE places (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            category VARCHAR, geom_wkb BLOB
        )
    """)
    poi_wkb = wkb.dumps(Point(-122.4, 37.8))
    con.execute(
        "INSERT INTO places VALUES ($1, $2, $3, $4, $5)",
        ["p1", "Exploratorium", "Exploratorium", "museum", poi_wkb],
    )
    con.close()

    return tmp_path


# --- Division search tests ---


def test_search_places_exact_match(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("California")
    assert len(results) == 1
    assert results[0].name == "California"
    assert results[0].subtype == "region"
    db.close()


def test_search_places_ilike_fallback(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("calif")
    assert len(results) == 1
    assert results[0].name == "California"
    db.close()


def test_search_places_with_type_filter(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("Georgia", place_type="region")
    assert len(results) == 1
    assert results[0].country == "US"
    db.close()


def test_search_places_with_context(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("Oakland", context="California")
    assert len(results) == 1
    assert results[0].region == "US-CA"
    db.close()


def test_search_places_no_results(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("Nonexistent")
    assert results == []
    db.close()


def test_search_places_geometry_loaded(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_places("California")
    assert results[0].geometry is not None
    assert results[0].geometry.geom_type == "Polygon"
    db.close()


def test_resolve_context_prefers_region(tmp_db):
    """'Georgia' as context should resolve to the US state, not the country."""
    db = PlaceDB(str(tmp_db))
    country, region = db._resolve_context("Georgia")
    assert country == "US"
    assert region == "US-GA"
    db.close()


# --- Feature search tests ---


def test_search_land_features(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_land_features("Mount Diablo")
    assert len(results) == 1
    assert results[0].feature_class == "peak"
    assert results[0].geometry is not None
    db.close()


def test_search_water_features(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_water_features("Lake Merritt")
    assert len(results) == 1
    assert results[0].feature_class == "lake"
    db.close()


def test_search_land_use(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_land_use("Golden Gate Park")
    assert len(results) == 1
    assert results[0].feature_class == "park"
    db.close()


# --- POI search tests ---


def test_search_pois(tmp_db):
    db = PlaceDB(str(tmp_db))
    results = db.search_pois("Exploratorium")
    assert len(results) == 1
    assert results[0].is_point is True
    assert results[0].geometry is not None
    db.close()


# --- Validation and edge cases ---


def test_search_feature_table_validation(tmp_db):
    db = PlaceDB(str(tmp_db))
    with pytest.raises(ValueError, match="Invalid feature table"):
        db._search_feature_table("bogus_table", "land", "anything")
    with pytest.raises(ValueError, match="Invalid column name"):
        db._search_feature_table("land_features", "land", "anything", class_column="bogus")
    db.close()


def test_missing_optional_dbs(tmp_path):
    """PlaceDB works with only divisions.duckdb present."""
    # Create a minimal divisions.duckdb only
    div_path = tmp_path / "divisions.duckdb"
    con = duckdb.connect(str(div_path))
    con.execute("""
        CREATE TABLE divisions (
            id VARCHAR, name VARCHAR, name_en VARCHAR,
            subtype VARCHAR, country VARCHAR, region VARCHAR
        )
    """)
    con.execute("CREATE TABLE division_areas (division_id VARCHAR, geom_wkb BLOB)")
    con.execute("INSERT INTO divisions VALUES ('d1', 'Test', NULL, 'locality', 'US', 'US-CA')")
    con.close()

    db = PlaceDB(str(tmp_path))
    assert db.features_con is None
    assert db.places_con is None
    assert db.search_land_features("anything") == []
    assert db.search_pois("anything") == []
    results = db.search_places("Test")
    assert len(results) == 1
    db.close()


def test_close(tmp_db):
    db = PlaceDB(str(tmp_db))
    db.close()  # should not raise
