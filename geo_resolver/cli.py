import argparse
import json
import sys

from .resolver import GeoResolver


def main():
    parser = argparse.ArgumentParser(
        prog="geo-resolve",
        description="Resolve natural language geographic queries to GeoJSON",
    )
    parser.add_argument("query", help="Geographic query (e.g. 'Bay Area')")
    parser.add_argument("-o", "--output", help="Output file path (.geojson)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--model", default=None, help="Override LLM model")
    args = parser.parse_args()

    kwargs = {}
    if args.model:
        kwargs["model"] = args.model

    resolver = GeoResolver(**kwargs)
    try:
        result = resolver.resolve(args.query)
    finally:
        resolver.close()

    indent = 2 if args.pretty else None
    geojson_str = json.dumps(result.geojson, indent=indent)

    if args.output:
        with open(args.output, "w") as f:
            f.write(geojson_str)
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        print(geojson_str)


if __name__ == "__main__":
    main()
