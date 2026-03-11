import json
import threading

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .schemas import ResolveRequest, ResolveResponse
from .dependencies import get_resolver

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest):
    resolver = get_resolver()
    try:
        result = resolver.resolve(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return ResolveResponse(
        query=result.query,
        geojson=result.geojson,
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
        try:
            result = resolver.resolve(req.query, on_step=on_step)
            q.put(("result", {
                "query": result.query,
                "geojson": result.geojson,
                "bounds": list(result.bounds),
                "area_km2": result.area_km2,
                "geometry_type": result.geometry.geom_type,
                "steps": result.steps,
            }))
        except Exception as e:
            q.put(("error", str(e)))

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

    return EventSourceResponse(event_generator())
