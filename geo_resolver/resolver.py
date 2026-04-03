import importlib.resources
import json
import logging
import os
import time
from collections.abc import Callable
from .db import PlaceDB
from .tools import ToolExecutor, TOOL_DEFINITIONS
from .models import ResolverResult, TokenUsage

_langfuse = None
_langfuse_checked = False


def _get_langfuse():
    """Lazy-init Langfuse after dotenv has loaded."""
    global _langfuse, _langfuse_checked
    if _langfuse_checked:
        return _langfuse
    _langfuse_checked = True
    try:
        from langfuse import Langfuse
        lf = Langfuse()
        if lf._tracing_enabled:
            _langfuse = lf
            logger.info("Langfuse tracing enabled (host=%s)", os.environ.get("LANGFUSE_HOST", "default"))
        else:
            logger.info("Langfuse tracing disabled (no credentials)")
    except Exception:
        logger.debug("Langfuse init failed", exc_info=True)
    return _langfuse

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

    def __init__(self, db, model=None, *, adapter=None, client=None, api_key=None, base_url=None):
        self.db = db

        if adapter is not None:
            self.adapter = adapter
            self.model = adapter.model
        else:
            # Backwards-compatible: build OpenAI adapter from client or credentials
            resolved_model = model or os.environ.get("GEO_RESOLVER_MODEL")
            if resolved_model is None:
                raise ValueError(
                    "model is required — pass it to LLMResolver() or set GEO_RESOLVER_MODEL env var"
                )
            from .providers.openai_adapter import OpenAIAdapter
            self.adapter = OpenAIAdapter(
                model=resolved_model,
                client=client,
                api_key=api_key or os.environ.get("GEO_RESOLVER_API_KEY"),
                base_url=base_url or os.environ.get("GEO_RESOLVER_BASE_URL"),
            )
            self.model = resolved_model

    def resolve(self, query: str, on_step=None, verbose: bool = False, max_iterations: int = 20) -> ResolverResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if len(query) > 2000:
            raise ValueError("query must be at most 2000 characters")

        resolve_start = time.monotonic()
        trace_id = None
        lf = _get_langfuse()
        if lf:
            try:
                trace_id = lf.create_trace_id()
            except Exception:
                pass
        executor = ToolExecutor(self.db)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        steps = []
        usage = TokenUsage()
        iteration_usages: list[TokenUsage] = []
        text_responses = 0

        def _emit(step: dict):
            steps.append(step)
            if on_step is not None:
                on_step(step)
            if verbose:
                print(f"  {step.get('message', step.get('tool', '...'))}")

        for i in range(max_iterations):
            iter_start = time.monotonic()
            response = self.adapter.chat_completion(messages=messages, tools=TOOL_DEFINITIONS)
            iter_latency = time.monotonic() - iter_start
            usage.prompt_tokens += response.usage.prompt_tokens
            usage.completion_tokens += response.usage.completion_tokens
            usage.total_tokens += response.usage.total_tokens
            iteration_usages.append(response.usage)

            # Log LLM call to Langfuse
            if lf and trace_id:
                try:
                    with lf.start_as_current_observation(
                        trace_id=trace_id,
                        name=f"llm-call-{i+1}",
                        type="generation",
                        model=self.model,
                        input=query if i == 0 else messages[-1].get("content", "")[:200] if messages else "",
                        output=response.content or "",
                        metadata={
                            "latency_s": round(iter_latency, 2),
                            "iteration": i + 1,
                            "tool_calls": len(response.tool_calls or []),
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                        },
                    ):
                        pass
                except Exception:
                    pass

            if response.tool_calls:
                if response.content:
                    _emit({"type": "thinking", "message": response.content.strip()})

                text_responses = 0

                # Build assistant message with tool_calls in OpenAI dict format
                assistant_msg = {"role": "assistant", "content": response.content}
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]
                messages.append(assistant_msg)

                for tc in response.tool_calls:
                    message = _describe_step(tc.name, tc.arguments)
                    result = executor.execute(tc.name, tc.arguments)
                    step = {
                        "tool": tc.name,
                        "args": tc.arguments,
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
                if response.content:
                    _emit({"type": "thinking", "message": response.content.strip()})

                if executor.final_id:
                    break
                if text_responses >= 2:
                    break
                messages.append({"role": "assistant", "content": response.content})
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
        total_latency = time.monotonic() - resolve_start

        # Log complete trace to Langfuse
        if lf and trace_id:
            try:
                with lf.start_as_current_observation(
                    trace_id=trace_id,
                    name="resolve",
                    input=query,
                    output=f"{geometry.geom_type} ({len(steps)} steps, {usage.total_tokens} tokens)",
                    metadata={
                        "model": self.model,
                        "latency_s": round(total_latency, 2),
                        "iterations": len(iteration_usages),
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                        "steps": len(steps),
                    },
                ):
                    pass
                lf.flush()
            except Exception:
                logger.debug("Failed to send Langfuse trace", exc_info=True)

        return ResolverResult(
            query=query, geometry=geometry, steps=steps, usage=usage,
            iteration_usage=iteration_usages, model=self.model,
        )

    async def resolve_async(
        self, query: str, on_step=None, verbose: bool = False, max_iterations: int = 20,
    ) -> ResolverResult:
        import asyncio
        return await asyncio.to_thread(
            self.resolve, query, on_step=on_step, verbose=verbose, max_iterations=max_iterations,
        )


class GeoResolver:
    """Unified entry point for geographic query resolution."""

    def __init__(
        self,
        data_dir: str | None = None,
        model: str | None = None,
        *,
        mode: str = "llm",
        provider: str | None = None,
        adapter=None,
        client=None,
        api_key: str | None = None,
        base_url: str | None = None,
        **provider_kwargs,
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

        if adapter is not None:
            self._llm = LLMResolver(self.db, adapter=adapter)
        elif provider is not None:
            from .providers import get_adapter
            built_adapter = get_adapter(
                resolved_model or "",
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                **provider_kwargs,
            )
            self._llm = LLMResolver(self.db, adapter=built_adapter)
        elif resolved_model or client:
            self._llm = LLMResolver(
                self.db, model=resolved_model, client=client,
                api_key=api_key, base_url=base_url,
            )

        # Direct resolver (always available)
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
