#!/usr/bin/env python3
"""Download Overture Maps data to local parquet files."""

import argparse

from geo_resolver.data.download import download, THEMES, DEFAULT_RELEASE

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Overture Maps data")
    parser.add_argument(
        "--theme", nargs="+", choices=list(THEMES.keys()),
        help="Themes to download (default: division division_area)",
    )
    parser.add_argument(
        "--release", default=DEFAULT_RELEASE,
        help=f"Overture Maps release version (default: {DEFAULT_RELEASE})",
    )
    args = parser.parse_args()
    download(args.theme, release=args.release)
