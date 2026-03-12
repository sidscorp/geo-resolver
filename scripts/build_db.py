#!/usr/bin/env python3
"""Convert downloaded parquet files into indexed DuckDB databases."""

import argparse
import os
import duckdb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def build_divisions():
    """Build divisions.duckdb from division parquet files."""
    db_path = os.path.join(DATA_DIR, "divisions.duckdb")
    division_path = os.path.join(DATA_DIR, "division.parquet")
    division_area_path = os.path.join(DATA_DIR, "division_area.parquet")

    for f in [division_path, division_area_path]:
        if not os.path.exists(f):
            print(f"  Missing {f}, skipping divisions build")
            return

    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")

    print("Importing divisions...")
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
    print(f"  {count} divisions")

    print("Creating division indexes...")
    con.execute("CREATE INDEX idx_div_name ON divisions(name)")
    con.execute("CREATE INDEX idx_div_name_en ON divisions(name_en)")
    con.execute("CREATE INDEX idx_div_subtype ON divisions(subtype)")
    con.execute("CREATE INDEX idx_div_country ON divisions(country)")

    print("Importing division areas (land only)...")
    con.execute(f"""
        CREATE TABLE division_areas AS
        SELECT
            division_id,
            ST_AsWKB(geometry) as geom_wkb
        FROM read_parquet('{division_area_path}')
        WHERE is_land = true
    """)
    count = con.execute("SELECT count(*) FROM division_areas").fetchone()[0]
    print(f"  {count} division areas")

    print("Creating area indexes...")
    con.execute("CREATE INDEX idx_area_divid ON division_areas(division_id)")

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    print(f"Database: {db_path} ({db_size:.0f} MB)")
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
        print("Importing land features...")
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
        print(f"  {count} land features")
        con.execute("CREATE INDEX idx_land_name ON land_features(name)")
        con.execute("CREATE INDEX idx_land_name_en ON land_features(name_en)")
        con.execute("CREATE INDEX idx_land_class ON land_features(class)")
        tables_built += 1
    else:
        print(f"  Missing {land_path}, skipping land features")

    water_path = os.path.join(DATA_DIR, "water.parquet")
    if os.path.exists(water_path):
        print("Importing water features...")
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
        print(f"  {count} water features")
        con.execute("CREATE INDEX idx_water_name ON water_features(name)")
        con.execute("CREATE INDEX idx_water_name_en ON water_features(name_en)")
        con.execute("CREATE INDEX idx_water_class ON water_features(class)")
        tables_built += 1
    else:
        print(f"  Missing {water_path}, skipping water features")

    land_use_path = os.path.join(DATA_DIR, "land_use.parquet")
    if os.path.exists(land_use_path):
        print("Importing land use features...")
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
        print(f"  {count} land use features")
        con.execute("CREATE INDEX idx_lu_name ON land_use_features(name)")
        con.execute("CREATE INDEX idx_lu_name_en ON land_use_features(name_en)")
        con.execute("CREATE INDEX idx_lu_subtype ON land_use_features(subtype)")
        tables_built += 1
    else:
        print(f"  Missing {land_use_path}, skipping land use features")

    if tables_built == 0:
        con.close()
        os.remove(db_path)
        print("No feature parquets found, skipping features.duckdb")
        return

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    print(f"Database: {db_path} ({db_size:.0f} MB)")
    con.close()


def build_places():
    """Build places.duckdb from place parquet file."""
    db_path = os.path.join(DATA_DIR, "places.duckdb")
    place_path = os.path.join(DATA_DIR, "place.parquet")

    if not os.path.exists(place_path):
        print(f"  Missing {place_path}, skipping places build")
        return

    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")

    print("Importing places (POIs)...")
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
    print(f"  {count} places")

    print("Creating place indexes...")
    con.execute("CREATE INDEX idx_place_name ON places(name)")
    con.execute("CREATE INDEX idx_place_name_en ON places(name_en)")
    con.execute("CREATE INDEX idx_place_category ON places(category)")

    db_size = os.path.getsize(db_path) / (1024 * 1024)
    print(f"Database: {db_path} ({db_size:.0f} MB)")
    con.close()


BUILDERS = {
    "divisions": build_divisions,
    "features": build_features,
    "places": build_places,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build DuckDB databases from parquet files")
    parser.add_argument(
        "--source", nargs="+", choices=list(BUILDERS.keys()),
        help="Sources to build (default: divisions)",
    )
    args = parser.parse_args()

    sources = args.source if args.source else ["divisions"]
    for source in sources:
        print(f"\n=== Building {source} ===")
        BUILDERS[source]()

    print("\nDone!")
