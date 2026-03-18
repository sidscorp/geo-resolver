# GeoResolver

Geographic boundary resolver with LLM and direct (no-LLM) modes. Natural language → polygon geometry via tool-calling against DuckDB of Overture Maps data.

## Architecture

```
GeoResolver (unified entry point)
├── mode="direct"  → DirectResolver (no LLM, smart DB search + ranking)
├── mode="llm"     → LLMResolver (LLM tool-calling loop)
└── mode="auto"    → tries direct, falls back to LLM
```

### Key Modules
- `resolver.py` — `GeoResolver` (entry point) + `LLMResolver` (LLM tool loop)
- `direct_resolver.py` — `DirectResolver` (scoring-based entity lookup, no LLM)
- `db.py` — `PlaceDB` (DuckDB queries across 3 databases: divisions, features, places)
- `tools.py` — `ToolExecutor` + `TOOL_DEFINITIONS` (OpenAI-format tool schemas)
- `models.py` — `Place`, `Feature`, `ResolverResult`, `TokenUsage`
- `spatial_ops.py` — Shapely wrappers (union, intersection, buffer, directional_subset)
- `prompts/system.txt` — LLM system prompt with tool descriptions + disambiguation guidance
- `providers/` — LLM provider adapters (OpenAI, Anthropic, Google, Bedrock, LiteLLM)
- `api/` — FastAPI server (routes, schemas, dependencies)
- `data/` — download + build scripts for Overture Maps parquet → DuckDB

### Data (in `data/` dir, gitignored)
- `divisions.duckdb` (~11GB) — 4.6M administrative divisions + 1.1M geometry areas
- `features.duckdb` (~10GB) — 988K land, 1.7M water, 1.5M land_use features
- `places.duckdb` (~420MB) — 2.3M POIs with confidence/address fields

### Disambiguation Fields (added 2026-03-17)
- Divisions: `population`, `prominence`
- Features: `wikidata`, `elevation` (land only)
- Land use: `wikidata`
- POIs: `confidence`, `country`, `region`, `locality`
- All search results include `centroid` (lat, lon)

## Stack
- **Backend:** FastAPI + DuckDB + Shapely + pyproj
- **LLM:** Provider adapter system — OpenAI, Anthropic, Google, Bedrock, LiteLLM (all optional deps)
- **Frontend:** Extracted to separate repo. Build artifacts in `frontend/dist/` (untracked).

### Provider Adapters

```python
# Auto-detect from model name
GeoResolver(model="claude-sonnet-4-20250514", api_key="...")      # → Anthropic
GeoResolver(model="gpt-4o", api_key="...")                # → OpenAI
GeoResolver(model="gemini-2.5-flash", api_key="...")      # → Google

# Explicit provider
GeoResolver(provider="bedrock", model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")
GeoResolver(provider="openai", model="...", base_url="https://openrouter.ai/api/v1")

# Backwards-compatible
GeoResolver(model="...", client=openai_client)  # pre-built OpenAI client
```

Each provider SDK is an optional dependency: `pip install geo-resolver[anthropic]`, etc.
Use `pip install geo-resolver[all-providers]` for everything.

## Environment
- `OPENROUTER_API_KEY` in `.env` (gitignored, never committed)
- Production: `geo-resolver.service` on port 8012, proxied via nginx at georesolver.snambiar.com

## Development
```bash
cd /home/snambiar/projects/geo-resolver
.venv/bin/uvicorn geo_resolver.api.main:app --port 8012 --reload
```

## Data Setup
```bash
# Download Overture Maps parquet files
.venv/bin/python -m geo_resolver.cli download-data --theme division division_area land water land_use place

# Build DuckDB databases
.venv/bin/python -m geo_resolver.cli build-db --source divisions features places
```

Data directory: `data/` (local) or `~/.geo-resolver/data/` (default). Set `GEO_RESOLVER_DATA_DIR` to override.

## Testing
```bash
.venv/bin/pytest tests/ -v              # Unit tests (130 tests, all mocked)
.venv/bin/python tests/visual_test.py   # Visual tests (generates PNGs in tests/visual_results/)
```

Visual test harness requires `pip install geo-resolver[visual]` (contextily, matplotlib, geopandas).

## Worktrees
Use `.worktrees/` directory (gitignored). Symlink `.venv` and `data` into worktree for shared deps and data.

## Current Work
- **Done:** Provider adapter system — OpenAI, Anthropic, Google, Bedrock, LiteLLM
- **Design doc:** `docs/plans/2026-03-17-provider-adapter-design.md`
