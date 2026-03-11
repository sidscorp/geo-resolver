import math
from shapely import Geometry
from shapely.ops import unary_union
from shapely.affinity import translate
from shapely.geometry import box


def union(geometries: list[Geometry]) -> Geometry:
    return unary_union(geometries)


def intersection(a: Geometry, b: Geometry) -> Geometry:
    return a.intersection(b)


def difference(a: Geometry, b: Geometry) -> Geometry:
    return a.difference(b)


def buffer_km(geometry: Geometry, distance_km: float) -> Geometry:
    deg = distance_km / 111.0
    return geometry.buffer(deg)


def directional_subset(geometry: Geometry, direction: str) -> Geometry:
    minx, miny, maxx, maxy = geometry.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    pad = 1.0

    clips = {
        "north": box(minx - pad, cy, maxx + pad, maxy + pad),
        "south": box(minx - pad, miny - pad, maxx + pad, cy),
        "east": box(cx, miny - pad, maxx + pad, maxy + pad),
        "west": box(minx - pad, miny - pad, cx, maxy + pad),
        "northeast": box(cx, cy, maxx + pad, maxy + pad),
        "northwest": box(minx - pad, cy, cx, maxy + pad),
        "southeast": box(cx, miny - pad, maxx + pad, cy),
        "southwest": box(minx - pad, miny - pad, cx, cy),
    }

    clip_box = clips.get(direction.lower())
    if clip_box is None:
        raise ValueError(f"Unknown direction: {direction}. Use: {list(clips.keys())}")

    return geometry.intersection(clip_box)
