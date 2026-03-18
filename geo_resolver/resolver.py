import importlib.resources
import json
import logging
import os
from collections.abc import Callable
from openai import OpenAI
from .db import PlaceDB
from .tools import ToolExecutor, TOOL_DEFINITIONS
from .models import ResolverResult, TokenUsage

logger = logging.getLogger(__name__)

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


class LLMResolver:
    """Resolve queries via LLM tool-calling loop."""

    def __init__(self, db, model=None, *, client=None, api_key=None, base_url=None):
        self.db = db
        self.model = model or os.environ.get("GEO_RESOLVER_MODEL")
        if self.model is None:
            raise ValueError(
                "model is required — pass it to LLMResolver() or set GEO_RESOLVER_MODEL env var"
            )
        if client is not None:
            self.client = client
        else:
            self.client = OpenAI(
                api_key=api_key or os.environ.get("GEO_RESOLVER_API_KEY"),
                base_url=base_url or os.environ.get("GEO_RESOLVER_BASE_URL"),
            )

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


class GeoResolver:
    """Unified entry point for geographic query resolution.

    Supports mode="llm" (LLM tool-calling), mode="direct" (no LLM),
    or mode="auto" (try direct, fall back to LLM).
    """

    def __init__(
        self,
        data_dir: str | None = None,
        model: str | None = None,
        *,
        mode: str = "llm",
        client=None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        if data_dir is None:
            data_dir = os.environ.get(
                "GEO_RESOLVER_DATA_DIR",
                os.path.expanduser("~/.geo-resolver/data"),
            )
        self.db = PlaceDB(data_dir)
        self.default_mode = mode

        # LLM resolver (optional)
        self._llm = None
        resolved_model = model or os.environ.get("GEO_RESOLVER_MODEL")
        if resolved_model or client:
            self._llm = LLMResolver(
                self.db, model=resolved_model, client=client,
                api_key=api_key, base_url=base_url,
            )

        # Direct resolver (always available once implemented)
        try:
            from .direct_resolver import DirectResolver
            self._direct = DirectResolver(self.db)
        except ImportError:
            self._direct = None

    @property
    def model(self):
        return self._llm.model if self._llm else None

    def resolve(self, query, mode=None, on_step=None, verbose=False, max_iterations=20):
        mode = mode or self.default_mode
        if mode == "direct":
            if self._direct is None:
                raise ValueError("Direct resolver not available — direct_resolver module not found")
            return self._direct.resolve(query, on_step=on_step, verbose=verbose)
        elif mode == "llm":
            if self._llm is None:
                raise ValueError("LLM resolver not configured — provide model/api_key")
            return self._llm.resolve(query, on_step=on_step, verbose=verbose, max_iterations=max_iterations)
        elif mode == "auto":
            return self._resolve_auto(query, on_step=on_step, verbose=verbose, max_iterations=max_iterations)
        else:
            raise ValueError(f"Unknown mode: {mode!r}. Use 'llm', 'direct', or 'auto'.")

    def _resolve_auto(self, query, on_step=None, verbose=False, max_iterations=20):
        spatial_keywords = [
            "excluding", "except", "minus", "without",
            "and", "plus", "combined",
            "overlap", "intersection",
            "north of", "south of", "east of", "west of",
        ]
        query_lower = query.lower()
        needs_llm = any(kw in query_lower for kw in spatial_keywords)

        if not needs_llm and self._direct is not None:
            try:
                result = self._direct.resolve(query, on_step=on_step, verbose=verbose)
                if result is not None:
                    return result
            except Exception:
                logger.debug("Direct resolve failed for '%s', falling back to LLM", query)

        if self._llm is None:
            raise ValueError("Query requires LLM but no model configured")
        return self._llm.resolve(query, on_step=on_step, verbose=verbose, max_iterations=max_iterations)

    async def resolve_async(self, query, mode=None, on_step=None, verbose=False, max_iterations=20):
        import asyncio
        return await asyncio.to_thread(
            self.resolve, query, mode=mode, on_step=on_step,
            verbose=verbose, max_iterations=max_iterations,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.db.close()
