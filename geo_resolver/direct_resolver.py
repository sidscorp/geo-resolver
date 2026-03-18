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

# Query keywords that hint at a preferred source type.
# Maps keyword patterns to (source, bonus) tuples.
_SOURCE_HINTS = [
    # Water features
    (re.compile(r"\blake\b", re.I), "water", 5.0),
    (re.compile(r"\briver\b", re.I), "water", 5.0),
    (re.compile(r"\bbay\b", re.I), "water", 5.0),
    (re.compile(r"\bocean\b", re.I), "water", 5.0),
    (re.compile(r"\bsea\b", re.I), "water", 5.0),
    (re.compile(r"\bfalls\b", re.I), "water", 3.0),
    (re.compile(r"\bstrait\b", re.I), "water", 5.0),
    # Land features
    (re.compile(r"\bmount(?:ain)?\b", re.I), "land", 5.0),
    (re.compile(r"\bpeak\b", re.I), "land", 5.0),
    (re.compile(r"\bisland\b", re.I), "land", 5.0),
    (re.compile(r"\bvolcano\b", re.I), "land", 5.0),
    (re.compile(r"\bglacier\b", re.I), "land", 5.0),
    (re.compile(r"\bcanyon\b", re.I), "land", 5.0),
    (re.compile(r"\bmountains\b", re.I), "land", 5.0),
    # Land use
    (re.compile(r"\bpark\b", re.I), "land_use", 5.0),
    (re.compile(r"\bcemetery\b", re.I), "land_use", 5.0),
    (re.compile(r"\breserve\b", re.I), "land_use", 5.0),
    (re.compile(r"\bnational park\b", re.I), "land_use", 5.0),
    # POIs / landmarks
    (re.compile(r"\btower\b", re.I), "place", 5.0),
    (re.compile(r"\bbridge\b", re.I), "place", 5.0),
    (re.compile(r"\bmonument\b", re.I), "place", 5.0),
    (re.compile(r"\bmuseum\b", re.I), "place", 5.0),
    (re.compile(r"\bstatue\b", re.I), "place", 5.0),
    (re.compile(r"\bairport\b", re.I), "place", 5.0),
    (re.compile(r"\bstadium\b", re.I), "place", 5.0),
    (re.compile(r"\bcastle\b", re.I), "place", 5.0),
    (re.compile(r"\bfort\b", re.I), "place", 3.0),
]


def _get_source_hints(query: str) -> dict[str, float]:
    """Return source-type bonuses implied by keywords in the query."""
    hints: dict[str, float] = {}
    for pattern, source, bonus in _SOURCE_HINTS:
        if pattern.search(query):
            hints[source] = max(hints.get(source, 0), bonus)
    return hints


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


def _score_place(place, query: str = ""):
    """Score a Place for ranking. Higher = better.

    Divisions (countries, states, cities) are the most common intent for
    geographic queries, so they get a strong baseline when they have
    geometry + meaningful population or prominence.
    """
    import math

    score = 0.0
    if place.geometry is None:
        return score

    score += 10.0

    # Subtype bonus: higher-level divisions are inherently more notable.
    # A "region" named Bavaria is more likely the user's intent than a
    # "Bavarian Forest" land feature.
    _SUBTYPE_BONUS = {
        "country": 10.0,
        "region": 7.0,
        "county": 4.0,
        "localadmin": 3.0,
        "locality": 2.0,
        "borough": 1.0,
        "neighborhood": 0.0,
    }
    score += _SUBTYPE_BONUS.get(place.subtype, 0.0)

    # Prominence: 0-100 scale in Overture data. Higher = more notable.
    # A city like NYC has ~79-100, a tiny hamlet has ~9.
    if place.prominence is not None:
        score += place.prominence * 0.1  # 0-10 range

    # Population: strong signal of importance. Log-scale to avoid
    # mega-cities completely dominating.
    if place.population is not None and place.population > 0:
        score += math.log10(place.population)  # 100K=5, 1M=6, 10M=7

    # Area bonus for divisions: larger divisions tend to be more notable
    # when comparing same-named places (e.g., Georgia US state vs Georgia country).
    if place.geometry is not None:
        area = place.geometry.area
        if area > 0:
            score += min(math.log10(area * 1e4) * 0.5, 2.0)

    # Exact name match bonus
    if query and place.name.lower() == query.lower():
        score += 3.0

    return score


def _score_feature(feature, query: str = "", source_hints: dict | None = None):
    """Score a Feature for ranking. Higher = better.

    Features (land, water, land_use, POIs) need strong signals to
    compete with divisions. Wikidata presence is a strong notability
    signal. Polygons beat points. Confidence helps disambiguate POIs.
    """
    score = 0.0
    if feature.geometry is None:
        return score

    score += 5.0  # lower baseline than divisions — divisions are the common case

    # Polygon > point (polygons are more useful as boundaries)
    if not feature.is_point:
        score += 3.0

    # Confidence (POIs, 0-1 scale)
    if feature.confidence is not None:
        score += feature.confidence * 2.0  # 0-2 range

    # Wikidata = notable entity. This is the strongest signal for features.
    if feature.wikidata:
        score += 5.0

    # Exact name match bonus
    if query:
        query_lower = query.lower()
        name_lower = feature.name.lower()
        if name_lower == query_lower:
            score += 3.0
        elif query_lower in name_lower:
            # Partial match: "Yellowstone" in "Yellowstone National Park"
            score += 1.5

    # Area-based tiebreaker: larger features are usually more notable.
    # This helps when multiple same-named features exist (e.g., Lake Tahoe
    # in Michigan vs California). Use log-scale so huge features don't
    # completely dominate.
    if feature.geometry is not None and not feature.is_point:
        import math
        area = feature.geometry.area  # in degrees², rough but sufficient for ranking
        if area > 0:
            score += min(math.log10(area * 1e6) * 0.5, 3.0)  # 0-3 range

    # Source-type hint bonus: if the query contains keywords like "Lake",
    # "Tower", "Park", boost features from the matching source.
    if source_hints and feature.source in source_hints:
        score += source_hints[feature.source]

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
        source_hints = _get_source_hints(name)

        # Search divisions
        places = self.db.search_places(name)
        for p in places:
            if p.geometry is not None:
                candidates.append(("place", p, _score_place(p, name)))
        if places:
            _emit({"type": "search", "message": f"Searched divisions: {len(places)} results"})

        # Search land features
        land = self.db.search_land_features(name)
        for f in land:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f, name, source_hints)))
        if land:
            _emit({"type": "search", "message": f"Searched land features: {len(land)} results"})

        # Search water features
        water = self.db.search_water_features(name)
        for f in water:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f, name, source_hints)))
        if water:
            _emit({"type": "search", "message": f"Searched water features: {len(water)} results"})

        # Search land use
        land_use = self.db.search_land_use(name)
        for f in land_use:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f, name, source_hints)))
        if land_use:
            _emit({"type": "search", "message": f"Searched land use: {len(land_use)} results"})

        # Search POIs
        pois = self.db.search_pois(name)
        for f in pois:
            if f.geometry is not None:
                candidates.append(("feature", f, _score_feature(f, name, source_hints)))
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
