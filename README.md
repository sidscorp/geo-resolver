# geo-resolver

Natural language to GeoJSON boundary resolver. Describe a geographic region in plain English and get back a precise boundary polygon.

## Features

- **Natural language queries** — "Northern California", "Manhattan excluding Central Park", "within 50km of the Eiffel Tower"
- **Multi-source data** — searches administrative divisions, land features, water bodies, land-use areas, and points of interest from Overture Maps
- **Spatial operations** — union, intersection, difference, buffer, and directional clipping composed automatically by an LLM agent
- **Streaming API** — real-time step-by-step progress via Server-Sent Events
- **Multi-provider LLM** — works with any OpenAI-compatible API (OpenAI, OpenRouter, Ollama, etc.) via LiteLLM

## Installation

```bash
pip install geo-resolver
```

## Data Setup

geo-resolver uses [Overture Maps](https://overturemaps.org/) data stored in local DuckDB databases. Download and build the data before first use:

```bash
# Download division boundaries (required)
geo-resolve download-data

# Download additional themes (land, water, land_use, POIs)
geo-resolve download-data --theme land water land_use place

# Build indexed DuckDB databases
geo-resolve build-db --source features places
```

By default, data is stored in `~/.geo-resolver/data/`. Set `GEO_RESOLVER_DATA_DIR` to use a different location.

## Quickstart

### Python API

```python
from geo_resolver import GeoResolver

with GeoResolver(model="openai/gpt-4o") as resolver:
    result = resolver.resolve("San Francisco Bay Area")
    result.save("bay_area.geojson")
    print(f"Area: {result.area_km2:.0f} km²")
```

### CLI

```bash
geo-resolve "Northern California" --output norcal.geojson --pretty
```

## Configuration

| Environment Variable | Description | Default |
|---|---|---|
| `GEO_RESOLVER_MODEL` | LLM model identifier (e.g. `openai/gpt-4o`) | *(required)* |
| `GEO_RESOLVER_API_KEY` | API key for the LLM provider | — |
| `GEO_RESOLVER_BASE_URL` | Base URL for the LLM API | — |
| `GEO_RESOLVER_DATA_DIR` | Path to DuckDB data directory | `~/.geo-resolver/data` |
| `GEO_RESOLVER_CORS_ORIGINS` | Comma-separated CORS origins for the API | `http://localhost:5173` |

## Web API

Install with API dependencies:

```bash
pip install geo-resolver[api]
```

Start the server:

```bash
uvicorn geo_resolver.api.main:app --host 127.0.0.1 --port 8012
```

Endpoints:

- `GET /api/health` — health check
- `POST /api/resolve` — synchronous resolve (JSON body: `{"query": "..."}`)
- `POST /api/resolve/stream` — streaming resolve via SSE

## Development

```bash
git clone https://github.com/sidscorp/geo-resolver.git
cd geo-resolver
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
pytest
```

## License

[MIT](LICENSE)
