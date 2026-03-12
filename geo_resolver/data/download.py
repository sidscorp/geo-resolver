"""Download Overture Maps data to local parquet files."""

import os
import duckdb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DEFAULT_RELEASE = "2026-02-18.0"

THEMES = {
    "division": {
        "s3": "theme=divisions/type=division",
        "filter": None,
    },
    "division_area": {
        "s3": "theme=divisions/type=division_area",
        "filter": None,
    },
    "land": {
        "s3": "theme=base/type=land",
        "filter": "class IN ('island','islet','mountain_range','peak','glacier','peninsula','cape','cliff','ridge','valley','volcano') AND names.primary IS NOT NULL",
    },
    "water": {
        "s3": "theme=base/type=water",
        "filter": "class IN ('lake','river','reservoir','bay','strait','ocean','sea','spring','waterfall') AND names.primary IS NOT NULL",
    },
    "land_use": {
        "s3": "theme=base/type=land_use",
        "filter": "subtype IN ('park','protected','recreation','cemetery','military','campground','entertainment') AND names.primary IS NOT NULL",
    },
    "place": {
        "s3": "theme=places/type=place",
        "filter": "categories.primary IN ('landmark_and_historical_building','park','beach','train_station','campground','museum','airport','amusement_park','golf_course','bridge','national_park','marina','ski_resort','castle','water_park','zoo','botanical_garden','aquarium','lighthouse','monument_and_memorial','tourist_attraction','stadium','sports_complex','performing_arts_theater','dam')",
    },
}


def download(themes: list[str] | None = None, release: str = DEFAULT_RELEASE):
    s3_base = f"s3://overturemaps-us-west-2/release/{release}"
    os.makedirs(DATA_DIR, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")

    to_download = themes if themes else ["division", "division_area"]

    for name in to_download:
        if name not in THEMES:
            print(f"  Unknown theme: {name} (available: {', '.join(THEMES.keys())})")
            continue

        theme = THEMES[name]
        outfile = os.path.join(DATA_DIR, f"{name}.parquet")
        if os.path.exists(outfile):
            print(f"  {outfile} already exists, skipping")
            continue

        s3_path = f"{s3_base}/{theme['s3']}/*"
        where = f"WHERE {theme['filter']}" if theme["filter"] else ""

        print(f"  Downloading {name}... (this may take a while)")
        con.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{s3_path}', filename=true, hive_partitioning=1)
                {where}
            ) TO '{outfile}' (FORMAT PARQUET)
        """)
        size_mb = os.path.getsize(outfile) / (1024 * 1024)
        print(f"  Saved {outfile} ({size_mb:.0f} MB)")

    con.close()
    print("Done!")
