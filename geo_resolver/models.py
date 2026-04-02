from dataclasses import dataclass, field
from functools import cached_property
import json
from shapely.geometry import shape, mapping
from shapely import Geometry
from pyproj import Geod


@dataclass
class Place:
    """An administrative division (country, state, county, city, etc.)."""
    id: str
    name: str
    subtype: str
    country: str | None
    region: str | None
    geometry: Geometry | None
    population: int | None = None
    prominence: int | None = None
    centroid: tuple[float, float] | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "subtype": self.subtype,
            "country": self.country,
            "region": self.region,
            "has_geometry": self.geometry is not None,
        }
        if self.population is not None:
            d["population"] = self.population
        if self.prominence is not None:
            d["prominence"] = self.prominence
        if self.centroid is not None:
            d["centroid"] = list(self.centroid)
        return d


@dataclass
class Feature:
    """A geographic feature (land, water, land-use, or point of interest)."""
    id: str
    name: str
    source: str  # "land", "water", "land_use", "place"
    feature_class: str  # "lake", "island", "park", "museum", etc.
    geometry: Geometry | None
    geom_type: str | None = None  # "Polygon", "LineString", "Point", etc.
    is_point: bool = False
    confidence: float | None = None
    country: str | None = None
    region: str | None = None
    locality: str | None = None
    wikidata: str | None = None
    elevation: int | None = None
    centroid: tuple[float, float] | None = None

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
        if self.confidence is not None:
            d["confidence"] = round(self.confidence, 3)
        if self.country is not None:
            d["country"] = self.country
        if self.region is not None:
            d["region"] = self.region
        if self.locality is not None:
            d["locality"] = self.locality
        if self.wikidata is not None:
            d["wikidata"] = self.wikidata
        if self.elevation is not None:
            d["elevation"] = self.elevation
        if self.centroid is not None:
            d["centroid"] = list(self.centroid)
        return d


@dataclass
class TokenUsage:
    """Accumulated token usage across all LLM calls in a resolve session."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def summary(self) -> str:
        """Human-readable one-line summary of token usage."""
        return (
            f"{self.prompt_tokens:,} prompt + "
            f"{self.completion_tokens:,} completion = "
            f"{self.total_tokens:,} total"
        )


@dataclass
class ResolverResult:
    """The output of :meth:`GeoResolver.resolve`."""
    query: str
    geometry: Geometry
    steps: list[dict] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    iteration_usage: list[TokenUsage] = field(default_factory=list)
    model: str | None = None

    @property
    def geojson(self) -> dict:
        """Return the geometry as a GeoJSON Feature dict."""
        return {
            "type": "Feature",
            "properties": {"query": self.query},
            "geometry": mapping(self.geometry),
        }

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Bounding box as ``(minx, miny, maxx, maxy)``."""
        return self.geometry.bounds

    @cached_property
    def area_km2(self) -> float:
        """Geodesic area in square kilometres."""
        geod = Geod(ellps="WGS84")
        area, _ = geod.geometry_area_perimeter(self.geometry)
        return abs(area) / 1e6

    def save(self, path: str):
        """Write the GeoJSON Feature to *path*."""
        with open(path, "w") as f:
            json.dump(self.geojson, f, indent=2)
