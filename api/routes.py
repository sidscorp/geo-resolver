import json
import threading

from fastapi import APIRouter, HTTPException
from shapely.geometry import mapping
from sse_starlette.sse import EventSourceResponse

from .schemas import ResolveRequest, ResolveResponse
from .dependencies import get_resolver

SIMPLIFY_TOLERANCE = 0.001

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
    simplified = result.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
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
    import asyncio
    import queue

    resolver = get_resolver()
    q: queue.Queue = queue.Queue()

    def on_step(step: dict):
        q.put(("step", step))

    def run():
        if not _resolve_semaphore.acquire(timeout=5):
            q.put(("error", "Too many concurrent requests, try again shortly"))
            return
        try:
            result = resolver.resolve(req.query, on_step=on_step)
            simplified = result.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
            geojson = {
                "type": "Feature",
                "properties": {"query": result.query},
                "geometry": mapping(simplified),
            }
            q.put(("result", {
                "query": result.query,
                "geojson": geojson,
                "bounds": list(result.bounds),
                "area_km2": result.area_km2,
                "geometry_type": result.geometry.geom_type,
                "steps": result.steps,
            }))
        except Exception as e:
            q.put(("error", str(e)))
        finally:
            _resolve_semaphore.release()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_generator():
        while True:
            try:
                event_type, data = q.get(timeout=0.1)
            except queue.Empty:
                if not thread.is_alive():
                    break
                await asyncio.sleep(0.05)
                continue

            yield {"event": event_type, "data": json.dumps(data)}

            if event_type in ("result", "error"):
                break

    return EventSourceResponse(event_generator(), ping=15)
