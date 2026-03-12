#!/usr/bin/env python3
"""Convert downloaded parquet files into indexed DuckDB databases."""

import argparse

from geo_resolver.data.build import BUILDERS

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
