import pytest
from shapely.geometry import box, MultiPolygon

from geo_resolver.spatial_ops import (
    union,
    intersection,
    difference,
    buffer_km,
    directional_subset,
)


def test_union(sample_polygon, sample_polygon_b):
    result = union([sample_polygon, sample_polygon_b])
    assert result.area > sample_polygon.area
    assert result.area < sample_polygon.area + sample_polygon_b.area


def test_union_disjoint():
    a = box(0, 0, 1, 1)
    b = box(5, 5, 6, 6)
    result = union([a, b])
    assert isinstance(result, MultiPolygon)
    assert result.area == pytest.approx(2.0)


def test_intersection(sample_polygon, sample_polygon_b):
    result = intersection(sample_polygon, sample_polygon_b)
    assert not result.is_empty
    assert result.area == pytest.approx(0.25)


def test_intersection_disjoint():
    a = box(0, 0, 1, 1)
    b = box(5, 5, 6, 6)
    result = intersection(a, b)
    assert result.is_empty


def test_difference(sample_polygon, sample_polygon_b):
    result = difference(sample_polygon, sample_polygon_b)
    assert not result.is_empty
    assert result.area == pytest.approx(0.75)


def test_buffer_km(sample_polygon):
    result = buffer_km(sample_polygon, 10)
    assert result.contains(sample_polygon)
    assert result.area > sample_polygon.area


def test_directional_subset_north(sample_polygon):
    result = directional_subset(sample_polygon, "north")
    assert not result.is_empty
    minx, miny, maxx, maxy = result.bounds
    assert miny >= 0.49


@pytest.mark.parametrize(
    "direction",
    ["north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"],
)
def test_directional_subset_all_directions(sample_polygon, direction):
    result = directional_subset(sample_polygon, direction)
    assert not result.is_empty


def test_directional_subset_invalid(sample_polygon):
    with pytest.raises(ValueError, match="Unknown direction"):
        directional_subset(sample_polygon, "up")
