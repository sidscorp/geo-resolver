import hashlib
import importlib.resources
import json
import logging
import os
import pickle
from collections import OrderedDict
from collections.abc import Callable
from openai import OpenAI
from .db import PlaceDB
from .tools import ToolExecutor, TOOL_DEFINITIONS
from .models import ResolverResult, TokenUsage

logger = logging.getLogger(__name__)


class _QueryCache:
    """Simple LRU cache for resolved queries, with optional disk persistence."""

    def __init__(self, maxsize: int = 256, cache_dir: str | None = None):
        self._cache: OrderedDict[str, ResolverResult] = OrderedDict()
        self._maxsize = maxsize
        self._cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            self._load_from_disk()

    @staticmethod
    def _normalize(query: str) -> str:
        return " ".join(query.lower().strip().split())

    def get(self, query: str) -> ResolverResult | None:
        key = self._normalize(query)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, query: str, result: ResolverResult):
        key = self._normalize(query)
        self._cache[key] = result
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)
        if self._cache_dir:
            self._save_entry(key, result)

    def _disk_path(self, key: str) -> str:
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return os.path.join(self._cache_dir, f"{h}.pkl")

    def _save_entry(self, key: str, result: ResolverResult):
        try:
            with open(self._disk_path(key), "wb") as f:
                pickle.dump((key, result), f)
        except Exception:
            pass

    def _load_from_disk(self):
        import glob
        for path in glob.glob(os.path.join(self._cache_dir, "*.pkl")):
            try:
                with open(path, "rb") as f:
                    key, result = pickle.load(f)
                self._cache[key] = result
            except Exception:
                pass

SYSTEM_PROMPT = (
    importlib.resources.files("geo_resolver") / "prompts" / "system.txt"
).read_text(encoding="utf-8")

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


_STEP_DISPATCH: dict[str, Callable] = {
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
        cache: bool = True,
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

        if cache:
            cache_dir = os.path.join(data_dir, ".cache")
            self._cache = _QueryCache(cache_dir=cache_dir)
        else:
            self._cache = None

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

        if self._cache is not None:
            cached = self._cache.get(query)
            if cached is not None:
                logger.info("Cache hit for '%s'", query)
                if on_step:
                    on_step({"type": "cache_hit", "message": f"Cache hit for '{query}'"})
                return cached

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
        resolved_name = executor.geometry_names.get(executor.final_id)
        result = ResolverResult(query=query, geometry=geometry, steps=steps, usage=usage, resolved_name=resolved_name)
        if self._cache is not None:
            self._cache.put(query, result)
        return result

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
