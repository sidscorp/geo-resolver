"""Convert downloaded parquet files into indexed DuckDB databases."""

import logging
import os
import duckdb

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("GEO_RESOLVER_DATA_DIR", os.path.expanduser("~/.geo-resolver/data"))


def build_divisions():
    """Build divisions.duckdb from division parquet files."""
    db_path = os.path.join(DATA_DIR, "divisions.duckdb")
    division_path = os.path.join(DATA_DIR, "division.parquet")
    division_area_path = os.path.join(DATA_DIR, "division_area.parquet")

    for f in [division_path, division_area_path]:
        if not os.path.exists(f):
            logger.warning("Missing %s, skipping divisions build", f)
            return

    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")

    logger.info("Importing divisions...")
    con.execute(f"""
        CREATE TABLE divisions AS
        SELECT
            id,
            names.primary as name,
            names.common.en as name_en,
            subtype,
            country,
            region
        FROM read_parquet('{division_path}')
    """)
    count = con.execute("SELECT count(*) FROM divisions").fetchone()[0]
    logger.info("  %d divisions", count)

    logger.info("Creating division indexes...")
    con.execute("CREATE INDEX idx_div_name ON divisions(name)")
    con.execute("CREATE INDEX idx_div_name_en ON divisions(name_en)")
    con.execute("CREATE INDEX idx_div_subtype ON divisions(subtype)")
    con.execute("CREATE INDEX idx_div_country ON divisions(country)")

    logger.info("Importing division areas (land only)...")
    con.execute(f"""
        CREATE TABLE division_areas AS
        SELECT
            division_id,
            ST_AsWKB(geometry) as geom_wkb
        FROM read_parquet('{division_area_path}')
        WHERE is_land = true
    """)
    count = con.execute("SELECT count(*) FROM division_areas").fetchone()[0]
    logger.info("  %d division areas", count)

    logger.info("Creating area indexes...")
    con.execute("CREATE INDEX idx_area_divid ON division_areas(division_id)")

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    logger.info("Database: %s (%.0f MB)", db_path, db_size)
    con.close()


def build_features():
    """Build features.duckdb from land, water, land_use parquet files."""
    db_path = os.path.join(DATA_DIR, "features.duckdb")

    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")

    tables_built = 0

    land_path = os.path.join(DATA_DIR, "land.parquet")
    if os.path.exists(land_path):
        logger.info("Importing land features...")
        con.execute(f"""
            CREATE TABLE land_features AS
            SELECT
                id,
                names.primary as name,
                names.common.en as name_en,
                class,
                ST_AsWKB(geometry) as geom_wkb,
                ST_GeometryType(geometry) as geom_type
            FROM read_parquet('{land_path}')
        """)
        count = con.execute("SELECT count(*) FROM land_features").fetchone()[0]
        logger.info("  %d land features", count)
        con.execute("CREATE INDEX idx_land_name ON land_features(name)")
        con.execute("CREATE INDEX idx_land_name_en ON land_features(name_en)")
        con.execute("CREATE INDEX idx_land_class ON land_features(class)")
        tables_built += 1
    else:
        logger.warning("Missing %s, skipping land features", land_path)

    water_path = os.path.join(DATA_DIR, "water.parquet")
    if os.path.exists(water_path):
        logger.info("Importing water features...")
        con.execute(f"""
            CREATE TABLE water_features AS
            SELECT
                id,
                names.primary as name,
                names.common.en as name_en,
                class,
                ST_AsWKB(geometry) as geom_wkb,
                ST_GeometryType(geometry) as geom_type
            FROM read_parquet('{water_path}')
        """)
        count = con.execute("SELECT count(*) FROM water_features").fetchone()[0]
        logger.info("  %d water features", count)
        con.execute("CREATE INDEX idx_water_name ON water_features(name)")
        con.execute("CREATE INDEX idx_water_name_en ON water_features(name_en)")
        con.execute("CREATE INDEX idx_water_class ON water_features(class)")
        tables_built += 1
    else:
        logger.warning("Missing %s, skipping water features", water_path)

    land_use_path = os.path.join(DATA_DIR, "land_use.parquet")
    if os.path.exists(land_use_path):
        logger.info("Importing land use features...")
        con.execute(f"""
            CREATE TABLE land_use_features AS
            SELECT
                id,
                names.primary as name,
                names.common.en as name_en,
                subtype,
                class,
                ST_AsWKB(geometry) as geom_wkb,
                ST_GeometryType(geometry) as geom_type
            FROM read_parquet('{land_use_path}')
        """)
        count = con.execute("SELECT count(*) FROM land_use_features").fetchone()[0]
        logger.info("  %d land use features", count)
        con.execute("CREATE INDEX idx_lu_name ON land_use_features(name)")
        con.execute("CREATE INDEX idx_lu_name_en ON land_use_features(name_en)")
        con.execute("CREATE INDEX idx_lu_subtype ON land_use_features(subtype)")
        tables_built += 1
    else:
        logger.warning("Missing %s, skipping land use features", land_use_path)

    if tables_built == 0:
        con.close()
        os.remove(db_path)
        logger.warning("No feature parquets found, skipping features.duckdb")
        return

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    logger.info("Database: %s (%.0f MB)", db_path, db_size)
    con.close()


def build_places():
    """Build places.duckdb from place parquet file."""
    db_path = os.path.join(DATA_DIR, "places.duckdb")
    place_path = os.path.join(DATA_DIR, "place.parquet")

    if not os.path.exists(place_path):
        logger.warning("Missing %s, skipping places build", place_path)
        return

    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")

    logger.info("Importing places (POIs)...")
    con.execute(f"""
        CREATE TABLE places AS
        SELECT
            id,
            names.primary as name,
            names.common.en as name_en,
            categories.primary as category,
            ST_AsWKB(geometry) as geom_wkb
        FROM read_parquet('{place_path}')
    """)
    count = con.execute("SELECT count(*) FROM places").fetchone()[0]
    logger.info("  %d places", count)

    logger.info("Creating place indexes...")
    con.execute("CREATE INDEX idx_place_name ON places(name)")
    con.execute("CREATE INDEX idx_place_name_en ON places(name_en)")
    con.execute("CREATE INDEX idx_place_category ON places(category)")

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    logger.info("Database: %s (%.0f MB)", db_path, db_size)
    con.close()


BUILDERS = {
    "divisions": build_divisions,
    "features": build_features,
    "places": build_places,
}
