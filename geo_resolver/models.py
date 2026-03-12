from dataclasses import dataclass, field
from typing import Any
import json
from shapely.geometry import shape, mapping
from shapely import Geometry


@dataclass
class Place:
    id: str
    name: str
    subtype: str
    country: str | None
    region: str | None
    geometry: Geometry | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "subtype": self.subtype,
            "country": self.country,
            "region": self.region,
            "has_geometry": self.geometry is not None,
        }


@dataclass
class Feature:
    id: str
    name: str
    source: str  # "land", "water", "land_use", "place"
    feature_class: str  # "lake", "island", "park", "museum", etc.
    geometry: Geometry | None
    geom_type: str | None = None  # "Polygon", "LineString", "Point", etc.
    is_point: bool = False

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "feature_class": self.feature_class,
            "has_geometry": self.geometry is not None,
            "is_point": self.is_point,
        }
        if self.geom_type:
            d["geom_type"] = self.geom_type
        return d


@dataclass
class ResolverResult:
    query: str
    geometry: Geometry
    steps: list[dict] = field(default_factory=list)

    @property
    def geojson(self) -> dict:
        return {
            "type": "Feature",
            "properties": {"query": self.query},
            "geometry": mapping(self.geometry),
        }

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.geometry.bounds

    @property
    def area_km2(self) -> float:
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
        area, _ = geod.geometry_area_perimeter(self.geometry)
        return abs(area) / 1e6

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.geojson, f, indent=2)
