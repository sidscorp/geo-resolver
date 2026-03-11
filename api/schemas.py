from pydantic import BaseModel


class ResolveRequest(BaseModel):
    query: str


class ResolveResponse(BaseModel):
    query: str
    geojson: dict
    bounds: list[float]
    area_km2: float
    geometry_type: str
    steps: list[dict]
