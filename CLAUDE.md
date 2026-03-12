# Geo-Resolver

Natural language → GeoJSON boundary resolver. LLM decomposes geographic queries into structured lookups + spatial operations against Overture Maps data.

## Architecture

- `geo_resolver/` — core library (resolver, tools, spatial_ops, db, models, cli)
- `geo_resolver/api/` — FastAPI web layer (SSE streaming)
- `geo_resolver/data/` — data download and DuckDB build logic
- `scripts/` — thin CLI wrappers for data download/build
- `data/` — DuckDB databases built from Overture Maps parquets (gitignored)
- `scratch/` — local working notes and task tracking (git-excluded)

Frontend lives in a separate repo: [geo-resolver-ui](https://github.com/sidscorp/geo-resolver-ui)

## Dev Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
# Data: python scripts/download_data.py && python scripts/build_db.py
```

Run: `make dev` (API on :8012)

## Conventions

- Python 3.10+. Use `str | None` union syntax, not `Optional[str]`.
- Type-hint all public functions. Add docstrings to public API methods.
- Tests in `tests/` using pytest. Run: `pytest`.
- Keep library code (`geo_resolver/`) free of side effects — no `load_dotenv()`, no hardcoded URLs.
- `GeoResolver` must remain provider-agnostic: accept `base_url`, `api_key`, or a pre-built `OpenAI` client.
- SQL: never interpolate user input into queries. Table/column names must be validated against whitelists.
- Makefile targets should use `$(CURDIR)` or relative paths, never absolute paths.

## Key Design Decisions

- DuckDB as embedded DB — no external database dependency
- OpenAI-compatible client — works with any provider (OpenRouter, OpenAI, Ollama, etc.)
- Streaming via SSE — real-time step-by-step progress
- Shapely for geometry ops, pyproj for coordinate transforms
- `scratch/TASKS.md` has the full task backlog for making this a publishable PyPI package
