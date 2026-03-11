#!/usr/bin/env python3
"""Download Overture Maps divisions data to local parquet files."""

import os
import sys
import duckdb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RELEASE = "2026-02-18.0"
S3_BASE = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=divisions"


def download():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")

    for dtype in ["division", "division_area"]:
        outfile = os.path.join(DATA_DIR, f"{dtype}.parquet")
        if os.path.exists(outfile):
            print(f"  {outfile} already exists, skipping")
            continue

        print(f"  Downloading {dtype}... (this may take a while)")
        s3_path = f"{S3_BASE}/type={dtype}/*"
        con.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{s3_path}', filename=true, hive_partitioning=1)
            ) TO '{outfile}' (FORMAT PARQUET)
        """)
        size_mb = os.path.getsize(outfile) / (1024 * 1024)
        print(f"  Saved {outfile} ({size_mb:.0f} MB)")

    con.close()
    print("Done!")


if __name__ == "__main__":
    download()
