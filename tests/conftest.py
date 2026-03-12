from unittest.mock import MagicMock

import pytest
from shapely.geometry import Point, box

from geo_resolver.models import Place, Feature


@pytest.fixture
def sample_polygon():
    return box(0, 0, 1, 1)


@pytest.fixture
def sample_polygon_b():
    return box(0.5, 0.5, 1.5, 1.5)


@pytest.fixture
def sample_point():
    return Point(0.5, 0.5)


@pytest.fixture
def mock_place(sample_polygon):
    return Place(
        id="div-001",
        name="TestPlace",
        subtype="locality",
        country="US",
        region="US-CA",
        geometry=sample_polygon,
    )


@pytest.fixture
def mock_feature(sample_polygon):
    return Feature(
        id="feat-001",
        name="TestLake",
        source="water",
        feature_class="lake",
        geometry=sample_polygon,
        geom_type="Polygon",
    )


@pytest.fixture
def mock_db(mock_place, mock_feature):
    from geo_resolver.db import PlaceDB

    db = MagicMock(spec=PlaceDB)
    db.search_places.return_value = [mock_place]
    db.search_land_features.return_value = [mock_feature]
    db.search_water_features.return_value = [mock_feature]
    db.search_land_use.return_value = [mock_feature]
    db.search_pois.return_value = [
        Feature(
            id="poi-001",
            name="TestPOI",
            source="place",
            feature_class="museum",
            geometry=Point(0.5, 0.5),
            geom_type="Point",
            is_point=True,
        )
    ]
    return db


def make_chat_response(tool_calls=None, content=None):
    """Build a mock OpenAI ChatCompletion response object."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response
