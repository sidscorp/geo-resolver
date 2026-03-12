from pydantic import BaseModel, Field


class ResolveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    simplify_tolerance: float = Field(0.001, ge=0, le=1)


class ResolveResponse(BaseModel):
    query: str
    geojson: dict
    bounds: list[float]
    area_km2: float
    geometry_type: str
    steps: list[dict]
