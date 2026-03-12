from geo_resolver.cli import build_parser


def test_resolve_subcommand_parsing():
    parser = build_parser()
    args = parser.parse_args(["resolve", "Bay Area"])
    assert args.command == "resolve"
    assert args.query == "Bay Area"
    assert args.max_iterations == 20
    assert args.output is None
    assert args.pretty is False


def test_resolve_max_iterations_custom():
    parser = build_parser()
    args = parser.parse_args(["resolve", "Bay Area", "--max-iterations", "5"])
    assert args.max_iterations == 5


def test_download_data_subcommand_parsing():
    parser = build_parser()
    args = parser.parse_args(["download-data"])
    assert args.command == "download-data"
    assert args.theme is None
    assert args.release == "2026-02-18.0"


def test_download_data_with_flags():
    parser = build_parser()
    args = parser.parse_args(["download-data", "--theme", "land", "water", "--release", "2025-01-01.0"])
    assert args.theme == ["land", "water"]
    assert args.release == "2025-01-01.0"


def test_build_db_subcommand_parsing():
    parser = build_parser()
    args = parser.parse_args(["build-db"])
    assert args.command == "build-db"
    assert args.source is None


def test_build_db_with_source():
    parser = build_parser()
    args = parser.parse_args(["build-db", "--source", "features", "places"])
    assert args.source == ["features", "places"]
