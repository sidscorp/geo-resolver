import argparse
import json
import sys

from . import __version__
from .resolver import GeoResolver


def _cmd_resolve(args):
    kwargs = {}
    if args.model:
        kwargs["model"] = args.model
    if args.api_key:
        kwargs["api_key"] = args.api_key
    if args.base_url:
        kwargs["base_url"] = args.base_url
    if args.data_dir:
        kwargs["data_dir"] = args.data_dir

    with GeoResolver(**kwargs) as resolver:
        result = resolver.resolve(args.query, mode=args.mode, max_iterations=args.max_iterations)

    indent = 2 if args.pretty else None
    geojson_str = json.dumps(result.geojson, indent=indent)

    if args.output:
        with open(args.output, "w") as f:
            f.write(geojson_str)
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        print(geojson_str)

    # Print token usage for LLM-based resolves
    if result.usage and result.usage.total_tokens > 0:
        model_info = f" ({result.model})" if result.model else ""
        print(f"\nToken usage{model_info}: {result.usage.summary()}", file=sys.stderr)
        if args.verbose:
            for i, iter_usage in enumerate(result.iteration_usage, 1):
                print(f"  Iteration {i}: {iter_usage.summary()}", file=sys.stderr)


def _cmd_download_data(args):
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .data.download import download, THEMES
    themes = args.theme if args.theme else None
    download(themes, release=args.release)


def _cmd_build_db(args):
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    from .data.build import BUILDERS
    sources = args.source if args.source else ["divisions"]
    for source in sources:
        logger.info("\n=== Building %s ===", source)
        BUILDERS[source]()
    logger.info("\nDone!")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geo-resolve",
        description="Resolve natural language geographic queries to GeoJSON",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # resolve subcommand
    resolve_parser = subparsers.add_parser("resolve", help="Resolve a geographic query to GeoJSON")
    resolve_parser.add_argument("query", help="Geographic query (e.g. 'Bay Area')")
    resolve_parser.add_argument("-o", "--output", help="Output file path (.geojson)")
    resolve_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    resolve_parser.add_argument("--model", default=None, help="LLM model name")
    resolve_parser.add_argument("--api-key", default=None, help="LLM API key")
    resolve_parser.add_argument("--base-url", default=None, help="LLM API base URL")
    resolve_parser.add_argument("--data-dir", default=None, help="Path to data directory")
    resolve_parser.add_argument(
        "--mode", choices=["llm", "direct", "auto"], default=None,
        help="Resolution mode: llm (default), direct (no LLM), auto",
    )
    resolve_parser.add_argument(
        "--max-iterations", type=int, default=20,
        help="Maximum LLM iterations (default: 20)",
    )
    resolve_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show per-iteration token usage breakdown",
    )

    # download-data subcommand
    from .data.download import THEMES, DEFAULT_RELEASE
    dl_parser = subparsers.add_parser("download-data", help="Download Overture Maps data")
    dl_parser.add_argument(
        "--theme", nargs="+", choices=list(THEMES.keys()),
        help="Themes to download (default: division division_area)",
    )
    dl_parser.add_argument(
        "--release", default=DEFAULT_RELEASE,
        help=f"Overture Maps release version (default: {DEFAULT_RELEASE})",
    )

    # build-db subcommand
    from .data.build import BUILDERS
    build_parser = subparsers.add_parser("build-db", help="Build DuckDB databases from parquet files")
    build_parser.add_argument(
        "--source", nargs="+", choices=list(BUILDERS.keys()),
        help="Sources to build (default: divisions)",
    )

    return parser


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "resolve":
        _cmd_resolve(args)
    elif args.command == "download-data":
        _cmd_download_data(args)
    elif args.command == "build-db":
        _cmd_build_db(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
