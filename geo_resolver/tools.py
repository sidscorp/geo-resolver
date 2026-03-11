import json
import uuid
from shapely import Geometry
from .db import PlaceDB
from . import spatial_ops

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": (
                "Search for a geographic place by name. Returns matching places "
                "with their type and whether they have polygon geometry. "
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
            "name": "union",
            "description": "Combine multiple geometries into one. Pass the geometry IDs returned by search_places or other operations.",
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
            "description": "Mark a geometry as the final result. Call this when you have the completed geometry that answers the user's query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geometry_id": {"type": "string", "description": "The geometry ID to return as the final result"},
                },
                "required": ["geometry_id"],
            },
        },
    },
]


class ToolExecutor:
    def __init__(self, db: PlaceDB):
        self.db = db
        self.geometries: dict[str, Geometry] = {}
        self.final_id: str | None = None

    def _store(self, geom: Geometry) -> str:
        gid = str(uuid.uuid4())[:8]
        self.geometries[gid] = geom
        return gid

    def _get(self, gid: str) -> Geometry:
        if gid not in self.geometries:
            raise ValueError(f"Unknown geometry ID: {gid}")
        return self.geometries[gid]

    def execute(self, name: str, args: dict) -> str:
        if name == "search_places":
            return self._search_places(**args)
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

    def _search_places(self, name: str, place_type: str = None, context: str = None) -> str:
        places = self.db.search_places(name, place_type, context)
        results = []
        for p in places:
            entry = p.to_dict()
            if p.geometry is not None:
                gid = self._store(p.geometry)
                entry["geometry_id"] = gid
            results.append(entry)
        return json.dumps(results, indent=2)

    def _union(self, geometry_ids: list[str]) -> str:
        geoms = [self._get(gid) for gid in geometry_ids]
        result = spatial_ops.union(geoms)
        gid = self._store(result)
        return json.dumps({"geometry_id": gid, "type": result.geom_type})

    def _intersection(self, geometry_id_a: str, geometry_id_b: str) -> str:
        result = spatial_ops.intersection(self._get(geometry_id_a), self._get(geometry_id_b))
        gid = self._store(result)
        return json.dumps({"geometry_id": gid, "type": result.geom_type})

    def _difference(self, geometry_id_a: str, geometry_id_b: str) -> str:
        result = spatial_ops.difference(self._get(geometry_id_a), self._get(geometry_id_b))
        gid = self._store(result)
        return json.dumps({"geometry_id": gid, "type": result.geom_type})

    def _buffer(self, geometry_id: str, distance_km: float) -> str:
        result = spatial_ops.buffer_km(self._get(geometry_id), distance_km)
        gid = self._store(result)
        return json.dumps({"geometry_id": gid, "type": result.geom_type})

    def _directional_subset(self, geometry_id: str, direction: str) -> str:
        result = spatial_ops.directional_subset(self._get(geometry_id), direction)
        gid = self._store(result)
        return json.dumps({"geometry_id": gid, "type": result.geom_type})

    def _finalize(self, geometry_id: str) -> str:
        self.final_id = geometry_id
        geom = self._get(geometry_id)
        return json.dumps({
            "status": "finalized",
            "geometry_id": geometry_id,
            "type": geom.geom_type,
            "bounds": list(geom.bounds),
        })
