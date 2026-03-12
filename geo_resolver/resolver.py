import json
import logging
import os
from litellm import OpenAI
from .db import PlaceDB
from .tools import ToolExecutor, TOOL_DEFINITIONS
from .models import ResolverResult, TokenUsage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a geographic boundary resolver. Given a natural language description of a region, you decompose it into structured lookups and spatial operations to produce the precise boundary polygon.

AVAILABLE DATA SOURCES:
- search_places — administrative divisions (countries, states, counties, cities, neighborhoods). Best for: "Bavaria", "San Francisco", "Manhattan".
- search_land_features — natural land features (islands, mountains, peaks, glaciers, volcanoes, peninsulas). Best for: "Ellis Island", "Rocky Mountains", "Mount Rainier".
- search_water_features — water bodies (lakes, rivers, bays, reservoirs, oceans). Best for: "Lake Tahoe", "Chesapeake Bay", "Mississippi River".
- search_land_use — land use areas (parks, nature reserves, recreation areas, cemeteries, military bases). Best for: "Central Park", "Yellowstone", "Arlington National Cemetery".
- search_pois — points of interest (landmarks, monuments, museums, stadiums, bridges, airports). Returns POINTS, must be buffered. Best for: "Statue of Liberty", "Eiffel Tower", "Golden Gate Bridge".

RESOLUTION STRATEGY:
1. For natural features/landmarks, try the specific feature tool first (land/water/land_use/pois).
2. For administrative areas, use search_places (divisions).
3. When uncertain, try the most specific tool first, then broaden.
4. Polygon results are always preferred over point+buffer.
5. POI points MUST be buffered: use suggested_buffer_km from results, or 0.15km for buildings, 1km for complexes.
6. Compositions across sources work normally — get Manhattan from divisions, Central Park from land_use, compute difference.
7. Rivers and some water features may be LineString geometry — buffer them if you need an area.

RULES:
- NEVER generate or guess coordinates. All geometry comes from search tools.
- geometry_id values are short IDs like "g1", "g2", "g3" — they are NOT the place UUIDs from the "id" field. Only use geometry_id values from the "geometry_id" field in search results or spatial operation outputs.
- Results with "has_geometry": false have NO geometry_id and cannot be finalized. You must find a result that HAS geometry.
- If searching with a specific place_type returns no geometry, retry WITHOUT place_type or with a different type (e.g. "county" instead of "locality"). Cities often have geometry as county but not as locality.
- Use spatial operations (union, intersection, difference, buffer, directional_subset) to compose geometries.
- When a query refers to an informal region (e.g. "Bay Area", "SoCal"), decompose it into its constituent administrative units and union them.
- Use the context parameter for disambiguation (e.g. "Portland" with context "Oregon" vs "Maine").
- Use place_type to narrow searches: country, region, county, localadmin, locality, borough, neighborhood.
- When done, call finalize with the geometry_id of the final result.
- Be efficient: make parallel tool calls when possible, minimize unnecessary searches.
- If a search returns no results with geometry, try broader or alternative names, different filters, or a different data source.
- The database uses local/primary names (e.g. "Deutschland" not "Germany", "Bayern" not "Bavaria") but also has English names indexed. Both are searchable.
- You MUST always call finalize when you have found a suitable geometry. Even if the match isn't perfect, finalize with the best available result.
- If you truly cannot find any matching geometry after trying multiple search strategies, call finalize with whatever closest match you found.

EXAMPLES:
- "San Francisco Bay Area" → search 9 Bay Area counties individually, union them
- "Northern California" → search California (region), then directional_subset with "north"
- "Manhattan excluding Central Park" → search_places("Manhattan") + search_land_use("Central Park") + difference
- "Within 50km of Paris" → search Paris (locality), buffer 50km
- "Bavaria, Germany" → search Bavaria with context Germany
- "Lake Tahoe" → search_water_features("Tahoe", feature_class="lake")
- "Ellis Island" → search_land_features("Ellis Island", feature_class="island")
- "Central Park" → search_land_use("Central Park", subtype="park")
- "Statue of Liberty" → search_pois("Statue of Liberty"), then buffer with suggested_buffer_km
- "Within 50km of the Eiffel Tower" → search_pois("Eiffel Tower"), buffer 50km"""

def _search_description(label: str, args: dict, qualifier_key: str) -> str:
    name = args.get("name", "?")
    qualifier = args.get(qualifier_key)
    suffix = f" ({qualifier})" if qualifier else ""
    return f"Searching {label} for {name}{suffix}..."


def _describe_places(args: dict) -> str:
    name = args.get("name", "?")
    ctx = args.get("context")
    ptype = args.get("place_type")
    parts = [f"Searching for {name}"]
    if ctx:
        parts.append(f"in {ctx}")
    if ptype:
        parts.append(f"({ptype})")
    return " ".join(parts) + "..."


_STEP_DISPATCH: dict[str, callable] = {
    "search_places": _describe_places,
    "search_land_features": lambda a: _search_description("land features", a, "feature_class"),
    "search_water_features": lambda a: _search_description("water features", a, "feature_class"),
    "search_land_use": lambda a: _search_description("land use areas", a, "subtype"),
    "search_pois": lambda a: _search_description("points of interest", a, "category"),
    "union": lambda a: f"Combining {len(a.get('geometry_ids', []))} regions...",
    "intersection": lambda a: "Finding overlap between two regions...",
    "difference": lambda a: "Subtracting one region from another...",
    "buffer": lambda a: f"Creating a {a.get('distance_km', '?')}km buffer zone...",
    "directional_subset": lambda a: f"Extracting {a.get('direction', '?')} portion...",
    "finalize": lambda a: "Finalizing result...",
}


def _describe_step(tool: str, args: dict) -> str:
    fn = _STEP_DISPATCH.get(tool)
    if fn:
        return fn(args)
    return f"Running {tool}..."


class GeoResolver:
    """Resolve natural language geographic queries into Shapely geometries.

    Uses an LLM tool-calling loop to search Overture Maps data and compose
    spatial operations until a final boundary polygon is produced.
    """

    def __init__(
        self,
        data_dir: str | None = None,
        model: str | None = None,
        *,
        client: OpenAI | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialise the resolver.

        Args:
            data_dir: Path to the DuckDB data directory. Defaults to
                ``GEO_RESOLVER_DATA_DIR`` env var or ``~/.geo-resolver/data``.
            model: LLM model identifier (e.g. ``"openai/gpt-4o"``). Falls back
                to ``GEO_RESOLVER_MODEL`` env var.
            client: Pre-built ``OpenAI`` client instance. If provided,
                *api_key* and *base_url* are ignored.
            api_key: API key passed to the default client constructor.
            base_url: Base URL passed to the default client constructor.
        """
        if data_dir is None:
            data_dir = os.environ.get(
                "GEO_RESOLVER_DATA_DIR",
                os.path.expanduser("~/.geo-resolver/data"),
            )
        self.db = PlaceDB(data_dir)

        self.model = (
            model
            or os.environ.get("GEO_RESOLVER_MODEL")
        )
        if self.model is None:
            raise ValueError(
                "model is required — pass it to GeoResolver() or set GEO_RESOLVER_MODEL env var"
            )

        if client is not None:
            self.client = client
        else:
            self.client = OpenAI(
                api_key=api_key or os.environ.get("GEO_RESOLVER_API_KEY"),
                base_url=base_url or os.environ.get("GEO_RESOLVER_BASE_URL"),
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def resolve(self, query: str, on_step=None, verbose: bool = False, max_iterations: int = 20) -> ResolverResult:
        """Resolve a natural language query into a ``ResolverResult``.

        Args:
            query: Geographic description (e.g. ``"Northern California"``).
            on_step: Optional callback invoked with a step dict after each
                tool call or LLM thinking message.
            verbose: If ``True``, print step summaries to stdout.

        Returns:
            A :class:`~geo_resolver.models.ResolverResult` containing the
            resolved geometry, the original query, and the step log.

        Raises:
            ValueError: If *query* is empty or exceeds 2000 characters.
            RuntimeError: If no matching geometry could be found.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if len(query) > 2000:
            raise ValueError("query must be at most 2000 characters")

        executor = ToolExecutor(self.db)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        steps = []
        usage = TokenUsage()
        text_responses = 0

        def _emit(step: dict):
            steps.append(step)
            if on_step is not None:
                on_step(step)
            if verbose:
                print(f"  {step.get('message', step.get('tool', '...'))}")

        for i in range(max_iterations):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
            if response.usage:
                usage.prompt_tokens += response.usage.prompt_tokens
                usage.completion_tokens += response.usage.completion_tokens
                usage.total_tokens += response.usage.total_tokens

            choice = response.choices[0]

            if choice.message.tool_calls:
                if choice.message.content:
                    _emit({"type": "thinking", "message": choice.message.content.strip()})

                text_responses = 0
                messages.append(choice.message)
                for tc in choice.message.tool_calls:
                    args = json.loads(tc.function.arguments)
                    message = _describe_step(tc.function.name, args)
                    result = executor.execute(tc.function.name, args)
                    step = {
                        "tool": tc.function.name,
                        "args": args,
                        "message": message,
                        "result_summary": result[:200],
                    }
                    _emit(step)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                if executor.final_id:
                    break
            else:
                text_responses += 1
                if choice.message.content:
                    _emit({"type": "thinking", "message": choice.message.content.strip()})

                if executor.final_id:
                    break
                if text_responses >= 2:
                    break
                messages.append(choice.message)
                messages.append({
                    "role": "user",
                    "content": (
                        "You must call finalize with a geometry_id. "
                        "If you found any place with geometry, finalize it. "
                        "If not, try searching with different terms or without filters."
                    ),
                })

        if executor.final_id is None:
            if executor.geometries:
                executor.final_id = max(
                    executor.geometries,
                    key=lambda gid: executor.geometries[gid].area,
                )
                logger.warning(
                    "No finalize call for query '%s', using largest geometry %s as fallback",
                    query, executor.final_id,
                )
            else:
                raise RuntimeError(
                    f"Could not resolve '{query}' — no matching geometries found"
                )

        geometry = executor.geometries[executor.final_id]
        return ResolverResult(query=query, geometry=geometry, steps=steps, usage=usage)

    async def resolve_async(
        self, query: str, on_step=None, verbose: bool = False, max_iterations: int = 20,
    ) -> ResolverResult:
        """Async wrapper around :meth:`resolve` using ``asyncio.to_thread``."""
        import asyncio
        return await asyncio.to_thread(
            self.resolve, query, on_step=on_step, verbose=verbose, max_iterations=max_iterations,
        )

    def close(self):
        """Close underlying database connections."""
        self.db.close()
