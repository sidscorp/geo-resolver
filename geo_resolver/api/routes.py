import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException
from shapely.geometry import mapping
from sse_starlette.sse import EventSourceResponse

from .schemas import ResolveRequest, ResolveResponse
from .dependencies import get_resolver

_resolve_semaphore = threading.Semaphore(3)

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest):
    if not _resolve_semaphore.acquire(timeout=5):
        raise HTTPException(status_code=429, detail="Too many concurrent requests, try again shortly")
    try:
        resolver = get_resolver()
        result = resolver.resolve(req.query)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _resolve_semaphore.release()
    simplified = result.geometry.simplify(req.simplify_tolerance, preserve_topology=True)
    geojson = {
        "type": "Feature",
        "properties": {"query": result.query},
        "geometry": mapping(simplified),
    }
    return ResolveResponse(
        query=result.query,
        geojson=geojson,
        bounds=list(result.bounds),
        area_km2=result.area_km2,
        geometry_type=result.geometry.geom_type,
        steps=result.steps,
    )


@router.post("/resolve/stream")
async def resolve_stream(req: ResolveRequest):
    resolver = get_resolver()
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def on_step(step: dict):
        loop.call_soon_threadsafe(q.put_nowait, ("step", step))

    def run():
        if not _resolve_semaphore.acquire(timeout=5):
            loop.call_soon_threadsafe(q.put_nowait, ("error", "Too many concurrent requests, try again shortly"))
            return
        try:
            result = resolver.resolve(req.query, on_step=on_step)
            simplified = result.geometry.simplify(req.simplify_tolerance, preserve_topology=True)
            geojson = {
                "type": "Feature",
                "properties": {"query": result.query},
                "geometry": mapping(simplified),
            }
            loop.call_soon_threadsafe(q.put_nowait, ("result", {
                "query": result.query,
                "geojson": geojson,
                "bounds": list(result.bounds),
                "area_km2": result.area_km2,
                "geometry_type": result.geometry.geom_type,
                "steps": result.steps,
            }))
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
        finally:
            _resolve_semaphore.release()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_generator():
        while True:
            event_type, data = await q.get()
            yield {"event": event_type, "data": json.dumps(data)}
            if event_type in ("result", "error"):
                break

    return EventSourceResponse(event_generator(), ping=15)
