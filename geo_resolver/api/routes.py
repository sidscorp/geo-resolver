import asyncio
import json
import logging
import threading
import time

from fastapi import APIRouter, HTTPException
from shapely.geometry import mapping
from sse_starlette.sse import EventSourceResponse

from .schemas import ResolveRequest, ResolveResponse, UsageResponse
from .dependencies import get_resolver
from .usage_tracker import log_request, get_stats

logger = logging.getLogger(__name__)

RESOLVE_TIMEOUT_SECONDS = 300
_resolve_semaphore = threading.Semaphore(3)

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest):
    logger.info("Resolve request: %s", req.query)
    t0 = time.monotonic()
    if not _resolve_semaphore.acquire(timeout=5):
        raise HTTPException(status_code=429, detail="Too many concurrent requests, try again shortly")
    try:
        resolver = get_resolver()
        result = resolver.resolve(req.query, mode=req.mode)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Resolve failed for query: %s", req.query)
        log_request(
            query=req.query, mode=req.mode,
            latency_s=time.monotonic() - t0,
            status="error", error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        _resolve_semaphore.release()
    latency = time.monotonic() - t0
    logger.info(
        "Resolve complete: query=%r area_km2=%.1f steps=%d latency=%.2fs",
        req.query, result.area_km2, len(result.steps), latency,
    )
    simplified = result.geometry.simplify(req.simplify_tolerance, preserve_topology=True)
    geojson = {
        "type": "Feature",
        "properties": {"query": result.query},
        "geometry": mapping(simplified),
    }
    usage_resp = None
    if result.usage and result.usage.total_tokens > 0:
        usage_resp = UsageResponse(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
        )
    log_request(
        query=req.query,
        mode=req.mode,
        model=getattr(result, "model", None),
        prompt_tokens=result.usage.prompt_tokens if result.usage else 0,
        completion_tokens=result.usage.completion_tokens if result.usage else 0,
        total_tokens=result.usage.total_tokens if result.usage else 0,
        latency_s=latency,
    )
    return ResolveResponse(
        query=result.query,
        geojson=geojson,
        bounds=list(result.bounds),
        area_km2=result.area_km2,
        geometry_type=result.geometry.geom_type,
        steps=result.steps,
        usage=usage_resp,
    )


@router.post("/resolve/stream")
async def resolve_stream(req: ResolveRequest):
    resolver = get_resolver()
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def on_step(step: dict):
        loop.call_soon_threadsafe(q.put_nowait, ("step", step))

    def run():
        if not _resolve_semaphore.acquire(timeout=5):
            loop.call_soon_threadsafe(q.put_nowait, ("error", "Too many concurrent requests, try again shortly"))
            return
        try:
            result = resolver.resolve(req.query, on_step=on_step, mode=req.mode)
            simplified = result.geometry.simplify(req.simplify_tolerance, preserve_topology=True)
            geojson = {
                "type": "Feature",
                "properties": {"query": result.query},
                "geometry": mapping(simplified),
            }
            usage_data = None
            if result.usage and result.usage.total_tokens > 0:
                usage_data = {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                }
            log_request(
                query=req.query,
                mode=req.mode,
                model=getattr(result, "model", None),
                prompt_tokens=result.usage.prompt_tokens if result.usage else 0,
                completion_tokens=result.usage.completion_tokens if result.usage else 0,
                total_tokens=result.usage.total_tokens if result.usage else 0,
            )
            loop.call_soon_threadsafe(q.put_nowait, ("result", {
                "query": result.query,
                "geojson": geojson,
                "bounds": list(result.bounds),
                "area_km2": result.area_km2,
                "geometry_type": result.geometry.geom_type,
                "steps": result.steps,
                "usage": usage_data,
            }))
        except Exception as exc:
            logger.exception("Streaming resolve failed for query: %s", req.query)
            log_request(
                query=req.query, mode=req.mode,
                status="error", error=str(exc),
            )
            loop.call_soon_threadsafe(q.put_nowait, ("error", "Internal server error"))
        finally:
            _resolve_semaphore.release()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_generator():
        while True:
            try:
                event_type, data = await asyncio.wait_for(
                    q.get(), timeout=RESOLVE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                yield {"event": "error", "data": json.dumps("Resolve timed out")}
                break
            yield {"event": event_type, "data": json.dumps(data)}
            if event_type in ("result", "error"):
                break

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/usage")
def usage(days: int = 30):
    return get_stats(days=days)
