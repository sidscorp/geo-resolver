import json
import logging
from shapely import Geometry
from .db import PlaceDB
from . import spatial_ops

logger = logging.getLogger(__name__)

POI_BUFFER_KM = {
    "landmark_and_historical_building": 0.15,
    "monument_and_memorial": 0.15,
    "lighthouse": 0.15,
    "castle": 0.3,
    "museum": 0.2,
    "aquarium": 0.2,
    "performing_arts_theater": 0.15,
    "bridge": 0.5,
    "dam": 0.5,
    "stadium": 0.3,
    "sports_complex": 0.5,
    "park": 1.0,
    "national_park": 5.0,
    "beach": 0.5,
    "botanical_garden": 0.3,
    "zoo": 0.5,
    "water_park": 0.3,
    "amusement_park": 0.5,
    "golf_course": 1.0,
    "campground": 1.0,
    "marina": 0.5,
    "ski_resort": 2.0,
    "airport": 3.0,
    "train_station": 0.2,
    "tourist_attraction": 0.3,
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": (
                "Search for administrative divisions by name. Returns matching places "
                "with their type and whether they have polygon geometry. "
                "Best for: countries, states/regions, counties, cities, boroughs, neighborhoods. "
                "Use place_type to filter (country, region, county, localadmin, "
                "locality, borough, neighborhood). Use context to disambiguate "
                "(e.g. context='California' when searching 'Oakland')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Place name to search for"},
                    "place_type": {
                        "type": "string",
                        "description": "Filter by type: country, region, county, localadmin, locality, borough, neighborhood",
                    },
                    "context": {
                        "type": "string",
                        "description": "Parent region for disambiguation (e.g. 'California', 'Germany')",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_land_features",
            "description": (
                "Search for natural land features like islands, mountains, peaks, "
                "glaciers, peninsulas, volcanoes, ridges, valleys, capes, cliffs. "
                "Results include confidence scores and location context for disambiguation. "
                "Best for: 'Ellis Island', 'Rocky Mountains', 'Mount Rainier', 'Cape Cod'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Feature name to search for"},
                    "feature_class": {
                        "type": "string",
                        "enum": ["island", "islet", "mountain_range", "peak", "glacier",
                                 "peninsula", "cape", "cliff", "ridge", "valley", "volcano"],
                        "description": "Filter by feature type",
                    },
                    "context": {
                        "type": "string",
                        "description": "Geographic context for disambiguation (e.g. 'New York', 'France')",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_water_features",
            "description": (
                "Search for water features like lakes, rivers, bays, reservoirs, "
                "straits, oceans, seas, springs, waterfalls. "
                "Results include confidence scores and location context for disambiguation. "
                "Best for: 'Lake Tahoe', 'Chesapeake Bay', 'Mississippi River'. "
                "Note: rivers may be LineString geometry, not Polygon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Water feature name to search for"},
                    "feature_class": {
                        "type": "string",
                        "enum": ["lake", "river", "reservoir", "bay", "strait",
                                 "ocean", "sea", "spring", "waterfall"],
                        "description": "Filter by water feature type",
                    },
                    "context": {
                        "type": "string",
                        "description": "Geographic context for disambiguation (e.g. 'New York', 'France')",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_land_use",
            "description": (
                "Search for land use areas like parks, nature reserves, recreation areas, "
                "cemeteries, military areas, campgrounds, entertainment areas. "
                "Results include confidence scores and location context for disambiguation. "
                "Best for: 'Central Park', 'Yellowstone', 'Arlington National Cemetery'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Land use area name to search for"},
                    "subtype": {
                        "type": "string",
                        "enum": ["park", "protected", "recreation", "cemetery",
                                 "military", "campground", "entertainment"],
                        "description": "Filter by land use type",
                    },
                    "context": {
                        "type": "string",
                        "description": "Geographic context for disambiguation (e.g. 'New York', 'France')",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_pois",
            "description": (
                "Search for points of interest like landmarks, monuments, museums, "
                "stadiums, bridges, airports, train stations, zoos, aquariums. "
                "Returns POINT geometries — you MUST apply a buffer to create an area. "
                "Use the suggested_buffer_km from results, or use buffer tool. "
                "Results include confidence scores and location context for disambiguation. "
                "Best for: 'Statue of Liberty', 'Eiffel Tower', 'Golden Gate Bridge'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "POI name to search for"},
                    "category": {
                        "type": "string",
                        "description": "Filter by category (e.g. 'landmark_and_historical_building', 'museum', 'airport', 'bridge', 'stadium')",
                    },
                    "context": {
                        "type": "string",
                        "description": "Geographic context for disambiguation (e.g. 'New York', 'France')",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "union",
            "description": "Combine multiple geometries into one. Pass the geometry IDs returned by search tools or other operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of geometry IDs to combine",
                    },
                },
                "required": ["geometry_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "intersection",
            "description": "Return the overlapping area of two geometries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id_a": {"type": "string"},
                    "geometry_id_b": {"type": "string"},
                },
                "required": ["geometry_id_a", "geometry_id_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "difference",
            "description": "Subtract geometry B from geometry A (A minus B).",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id_a": {"type": "string"},
                    "geometry_id_b": {"type": "string"},
                },
                "required": ["geometry_id_a", "geometry_id_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buffer",
            "description": "Expand a geometry by a distance in kilometers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id": {"type": "string"},
                    "distance_km": {"type": "number", "description": "Buffer distance in kilometers"},
                },
                "required": ["geometry_id", "distance_km"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "directional_subset",
            "description": "Get a directional portion of a geometry (e.g. 'Northern California'). Clips the geometry to the specified half or quadrant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"],
                    },
                },
                "required": ["geometry_id", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize",
            "description": "Mark a geometry as the final result. Call this when you have the completed geometry that answers the user's query. The geometry_id must be one returned by a search or spatial operation (e.g. 'g1', 'g2'), NOT a place UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id": {"type": "string", "description": "The geometry ID (e.g. 'g1', 'g2') to return as the final result"},
                },
                "required": ["geometry_id"],
            },
        },
    },
]


class ToolExecutor:
    """Execute LLM tool calls against a :class:`PlaceDB` and manage geometry state."""

    def __init__(self, db: PlaceDB):
        self.db = db
        self.geometries: dict[str, Geometry] = {}
        self.final_id: str | None = None
        self._counter = 0

    def _store(self, geom: Geometry) -> str:
        self._counter += 1
        gid = f"g{self._counter}"
        self.geometries[gid] = geom
        return gid

    def _get(self, gid: str) -> Geometry:
        if gid not in self.geometries:
            hint = ""
            if len(gid) > 10:
                hint = " (You passed a place UUID, not a geometry_id. Use the 'geometry_id' field from search results, e.g. 'g1', 'g2'.)"
            available = list(self.geometries.keys())
            raise ValueError(f"Unknown geometry ID: {gid}.{hint} Available: {available}")
        return self.geometries[gid]

    def execute(self, name: str, args: dict) -> str:
        """Dispatch a tool call by *name* with *args*, returning a JSON string."""
        try:
            if name == "search_places":
                return self._search_places(**args)
            elif name == "search_land_features":
                return self._search_land_features(**args)
            elif name == "search_water_features":
                return self._search_water_features(**args)
            elif name == "search_land_use":
                return self._search_land_use(**args)
            elif name == "search_pois":
                return self._search_pois(**args)
            elif name == "union":
                return self._union(**args)
            elif name == "intersection":
                return self._intersection(**args)
            elif name == "difference":
                return self._difference(**args)
            elif name == "buffer":
                return self._buffer(**args)
            elif name == "directional_subset":
                return self._directional_subset(**args)
            elif name == "finalize":
                return self._finalize(**args)
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            logger.warning("Tool %s failed with args %s: %s", name, args, e, exc_info=True)
            return json.dumps({"error": str(e)})

    def _format_search_results(self, items: list, add_buffer_hint: bool = False) -> str:
        results = []
        for item in items:
            entry = item.to_dict()
            if item.geometry is not None:
                gid = self._store(item.geometry)
                entry["geometry_id"] = gid
            if add_buffer_hint:
                entry["suggested_buffer_km"] = POI_BUFFER_KM.get(item.feature_class, 0.3)
            results.append(entry)
        return json.dumps(results, indent=2)

    def _search_places(self, name: str = "", place_type: str | None = None, context: str | None = None) -> str:
        if not name:
            return json.dumps({"error": "name is required for search_places"})
        return self._format_search_results(self.db.search_places(name, place_type, context))

    def _search_land_features(self, name: str = "", feature_class: str | None = None, context: str | None = None) -> str:
        if not name:
            return json.dumps({"error": "name is required for search_land_features"})
        return self._format_search_results(self.db.search_land_features(name, feature_class))

    def _search_water_features(self, name: str = "", feature_class: str | None = None, context: str | None = None) -> str:
        if not name:
            return json.dumps({"error": "name is required for search_water_features"})
        return self._format_search_results(self.db.search_water_features(name, feature_class))

    def _search_land_use(self, name: str = "", subtype: str | None = None, context: str | None = None) -> str:
        if not name:
            return json.dumps({"error": "name is required for search_land_use"})
        return self._format_search_results(self.db.search_land_use(name, subtype))

    def _search_pois(self, name: str = "", category: str | None = None, context: str | None = None) -> str:
        if not name:
            return json.dumps({"error": "name is required for search_pois"})
        return self._format_search_results(self.db.search_pois(name, category, context=context), add_buffer_hint=True)

    def _spatial_result_json(self, result: Geometry) -> str:
        gid = self._store(result)
        data: dict = {"geometry_id": gid, "type": result.geom_type}
        if result.is_empty:
            data["warning"] = "result geometry is empty"
        return json.dumps(data)

    def _union(self, geometry_ids: list[str]) -> str:
        geoms = [self._get(gid) for gid in geometry_ids]
        return self._spatial_result_json(spatial_ops.union(geoms))

    def _intersection(self, geometry_id_a: str, geometry_id_b: str) -> str:
        result = spatial_ops.intersection(self._get(geometry_id_a), self._get(geometry_id_b))
        return self._spatial_result_json(result)

    def _difference(self, geometry_id_a: str, geometry_id_b: str) -> str:
        result = spatial_ops.difference(self._get(geometry_id_a), self._get(geometry_id_b))
        return self._spatial_result_json(result)

    def _buffer(self, geometry_id: str, distance_km: float) -> str:
        return self._spatial_result_json(spatial_ops.buffer_km(self._get(geometry_id), distance_km))

    def _directional_subset(self, geometry_id: str, direction: str) -> str:
        return self._spatial_result_json(spatial_ops.directional_subset(self._get(geometry_id), direction))

    def _finalize(self, geometry_id: str) -> str:
        self.final_id = geometry_id
        geom = self._get(geometry_id)
        self.geometries = {geometry_id: geom}
        return json.dumps({
            "status": "finalized",
            "geometry_id": geometry_id,
            "type": geom.geom_type,
            "bounds": list(geom.bounds),
        })
