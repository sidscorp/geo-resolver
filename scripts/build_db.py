#!/usr/bin/env python3
"""Convert downloaded parquet files into an indexed DuckDB database."""

import os
import duckdb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "divisions.duckdb")


def build():
    division_path = os.path.join(DATA_DIR, "division.parquet")
    division_area_path = os.path.join(DATA_DIR, "division_area.parquet")

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    con = duckdb.connect(DB_PATH)
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

    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"Database: {DB_PATH} ({db_size:.0f} MB)")
    con.close()
    print("Done!")


if __name__ == "__main__":
    build()
