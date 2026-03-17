"""Direct resolver — resolve geographic queries without an LLM.

Searches all five data sources (divisions, land features, water features,
land use, POIs), ranks candidates by disambiguation signals, and returns
the best match.
"""

import logging
import re
from .db import PlaceDB
from .models import ResolverResult, Feature, Place
from .tools import POI_BUFFER_KM
from . import spatial_ops

logger = logging.getLogger(__name__)

# Patterns for simple spatial modifiers
_DIRECTIONAL_RE = re.compile(
    r"^(northern|southern|eastern|western|north|south|east|west|"
    r"northeast|northwest|southeast|southwest)\s+(.+)$",
    re.IGNORECASE,
)
_BUFFER_RE = re.compile(
    r"^within\s+([\d.]+)\s*km\s+of\s+(.+)$",
    re.IGNORECASE,
)

_DIRECTION_MAP = {
    "northern": "north", "southern": "south",
    "eastern": "east", "western": "west",
    "north": "north", "south": "south",
    "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest",
    "southeast": "southeast", "southwest": "southwest",
}


def _score_place(place):
    """Score a Place for ranking. Higher = better."""
    score = 0.0
    if place.geometry is not None:
        score += 10.0
    if place.prominence is not None:
        score += min(place.prominence / 25.0, 1.0)
    if place.population is not None and place.population > 0:
        score += min(place.population / 10_000_000, 1.0)
    return score


def _score_feature(feature):
    """Score a Feature for ranking. Higher = better."""
    score = 0.0
    if feature.geometry is not None:
        score += 10.0
        if not feature.is_point:
            score += 2.0
    if feature.confidence is not None:
        score += feature.confidence
    if feature.wikidata:
        score += 1.5
    return score


class DirectResolver:
    """Resolve geographic queries by direct DB search + ranking, no LLM."""

    def __init__(self, db: PlaceDB):
        self.db = db

    def resolve(self, query: str, on_step=None, verbose=False) -> ResolverResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        steps = []
        def _emit(step):
            steps.append(step)
            if on_step:
                on_step(step)
            if verbose:
                print(f"  {step.get('message', '...')}")

        # Check for directional modifier
        dir_match = _DIRECTIONAL_RE.match(query.strip())
        if dir_match:
            direction = _DIRECTION_MAP[dir_match.group(1).lower()]
            entity_name = dir_match.group(2).strip()
            _emit({"type": "parse", "message": f"Parsed: {direction} of '{entity_name}'"})
            result = self._search_all(entity_name, _emit, steps)
            if result is None:
                raise RuntimeError(f"Could not resolve '{entity_name}'")
            geom = spatial_ops.directional_subset(result.geometry, direction)
            _emit({"type": "spatial", "message": f"Applied directional_subset: {direction}"})
            return ResolverResult(query=query, geometry=geom, steps=steps)

        # Check for buffer modifier
        buf_match = _BUFFER_RE.match(query.strip())
        if buf_match:
            distance_km = float(buf_match.group(1))
            entity_name = buf_match.group(2).strip()
            _emit({"type": "parse", "message": f"Parsed: {distance_km}km buffer around '{entity_name}'"})
            result = self._search_all(entity_name, _emit, steps)
            if result is None:
                raise RuntimeError(f"Could not resolve '{entity_name}'")
            geom = spatial_ops.buffer_km(result.geometry, distance_km)
            _emit({"type": "spatial", "message": f"Applied buffer: {distance_km}km"})
            return ResolverResult(query=query, geometry=geom, steps=steps)

        # Simple entity lookup
        result = self._search_all(query.strip(), _emit, steps)
        if result is None:
            raise RuntimeError(f"Could not resolve '{query}' — no matching geometries found")
        return result

    def _search_all(self, name, _emit, steps=None) -> ResolverResult | None:
        """Search all sources, rank, return best as ResolverResult."""
        if steps is None:
            steps = []
        candidates = []

        # Search divisions
        places = self.db.search_places(name)
        for p in places:
            if p.geometry is not None:
                candidates.append(("place", p, _score_place(p)))
        if places:
            _emit({"type": "search", "message": f"Searched divisions: {len(places)} results"})

        # Search land features
        land = self.db.search_land_features(name)
        for f in land:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f)))
        if land:
            _emit({"type": "search", "message": f"Searched land features: {len(land)} results"})

        # Search water features
        water = self.db.search_water_features(name)
        for f in water:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f)))
        if water:
            _emit({"type": "search", "message": f"Searched water features: {len(water)} results"})

        # Search land use
        land_use = self.db.search_land_use(name)
        for f in land_use:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f)))
        if land_use:
            _emit({"type": "search", "message": f"Searched land use: {len(land_use)} results"})

        # Search POIs
        pois = self.db.search_pois(name)
        for f in pois:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f)))
        if pois:
            _emit({"type": "search", "message": f"Searched POIs: {len(pois)} results"})

        if not candidates:
            _emit({"type": "search", "message": f"No results found for '{name}'"})
            return None

        # Sort by score descending
        candidates.sort(key=lambda c: c[2], reverse=True)
        best_type, best, best_score = candidates[0]
        _emit({"type": "select", "message": f"Selected: {best.name} (score={best_score:.2f}, type={best_type})"})

        geom = best.geometry
        # Buffer points
        if isinstance(best, Feature) and best.is_point:
            buffer_km_val = POI_BUFFER_KM.get(best.feature_class, 0.3)
            geom = spatial_ops.buffer_km(geom, buffer_km_val)
            _emit({"type": "spatial", "message": f"Buffered point by {buffer_km_val}km"})

        return ResolverResult(query=name, geometry=geom, steps=steps)
