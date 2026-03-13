from pyproj import Transformer
from shapely import Geometry
from shapely.ops import unary_union, transform
from shapely.geometry import box


def union(geometries: list[Geometry]) -> Geometry:
    """Return the union of all *geometries*."""
    return unary_union(geometries)


def intersection(a: Geometry, b: Geometry) -> Geometry:
    """Return the geometric intersection of *a* and *b*."""
    return a.intersection(b)


def difference(a: Geometry, b: Geometry) -> Geometry:
    """Return *a* minus *b* (geometric difference)."""
    return a.difference(b)


def _utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


def buffer_km(geometry: Geometry, distance_km: float) -> Geometry:
    """Buffer *geometry* by *distance_km* kilometres using a local UTM projection.

    Note: the UTM zone is determined from the geometry centroid. For geometries
    spanning more than ~6 degrees of longitude, the single-zone projection may
    introduce distortion at the edges.
    """
    centroid = geometry.centroid
    epsg = _utm_epsg(centroid.x, centroid.y)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
    projected = transform(to_utm, geometry)
    buffered = projected.buffer(distance_km * 1000)
    return transform(to_wgs, buffered)


def directional_subset(geometry: Geometry, direction: str) -> Geometry:
    """Clip *geometry* to a compass *direction* (e.g. ``"north"``, ``"southwest"``)."""
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
