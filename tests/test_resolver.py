import asyncio
import json
from unittest.mock import MagicMock, patch, call

import pytest

from geo_resolver.resolver import GeoResolver
from geo_resolver.models import ResolverResult, TokenUsage
from tests.conftest import make_chat_response


def _make_tool_call(name, arguments, tc_id="tc1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_simple(mock_openai_cls, mock_db_cls, mock_db, mock_place):
    mock_db_cls.return_value = mock_db
    client = MagicMock()
    mock_openai_cls.return_value = client

    # Turn 1: LLM calls search_places
    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    resp1 = make_chat_response(tool_calls=[search_tc])

    # Turn 2: LLM calls finalize
    finalize_tc = _make_tool_call("finalize", {"geometry_id": "g1"}, "tc2")
    resp2 = make_chat_response(tool_calls=[finalize_tc])

    client.chat.completions.create.side_effect = [resp1, resp2]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = resolver.resolve("TestPlace")

    assert isinstance(result, ResolverResult)
    assert result.query == "TestPlace"
    assert not result.geometry.is_empty


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_empty_query_raises(mock_openai_cls, mock_db_cls):
    mock_db_cls.return_value = MagicMock()
    client = MagicMock()
    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)

    with pytest.raises(ValueError, match="non-empty"):
        resolver.resolve("")


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_long_query_raises(mock_openai_cls, mock_db_cls):
    mock_db_cls.return_value = MagicMock()
    client = MagicMock()
    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)

    with pytest.raises(ValueError, match="2000"):
        resolver.resolve("x" * 2001)


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_no_geometry_raises(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    # Make search return no geometry
    from geo_resolver.models import Place
    mock_db.search_places.return_value = [
        Place(id="x", name="NoGeom", subtype="locality", country=None, region=None, geometry=None)
    ]
    client = MagicMock()

    search_tc = _make_tool_call("search_places", {"name": "NoGeom"}, "tc1")
    resp1 = make_chat_response(tool_calls=[search_tc])
    # LLM gives up with text
    resp2 = make_chat_response(content="I can't find geometry")
    resp3 = make_chat_response(content="Still nothing")

    client.chat.completions.create.side_effect = [resp1, resp2, resp3]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)

    with pytest.raises(RuntimeError, match="no matching geometries"):
        resolver.resolve("NoGeom")


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_fallback_to_largest(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    # LLM calls search but never calls finalize, then gives text responses
    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    resp1 = make_chat_response(tool_calls=[search_tc])
    resp2 = make_chat_response(content="Thinking...")
    resp3 = make_chat_response(content="Still thinking...")

    client.chat.completions.create.side_effect = [resp1, resp2, resp3]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = resolver.resolve("TestPlace")

    # Falls back to largest geometry
    assert isinstance(result, ResolverResult)
    assert not result.geometry.is_empty


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_on_step_callback(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    finalize_tc = _make_tool_call("finalize", {"geometry_id": "g1"}, "tc2")
    resp1 = make_chat_response(tool_calls=[search_tc])
    resp2 = make_chat_response(tool_calls=[finalize_tc])
    client.chat.completions.create.side_effect = [resp1, resp2]

    steps = []
    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    resolver.resolve("TestPlace", on_step=lambda s: steps.append(s))

    assert len(steps) >= 2
    assert any(s.get("tool") == "search_places" for s in steps)
    assert any(s.get("tool") == "finalize" for s in steps)


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_max_iterations(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    # LLM keeps searching and never finalizes
    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    resp = make_chat_response(tool_calls=[search_tc])
    # Provide enough responses for max_iterations=2
    client.chat.completions.create.side_effect = [resp, resp, resp]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = resolver.resolve("TestPlace", max_iterations=2)

    # Should fall back to largest geometry after 2 iterations
    assert isinstance(result, ResolverResult)
    assert client.chat.completions.create.call_count == 2


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_tracks_usage(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    resp1 = make_chat_response(tool_calls=[search_tc])
    resp1.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)

    finalize_tc = _make_tool_call("finalize", {"geometry_id": "g1"}, "tc2")
    resp2 = make_chat_response(tool_calls=[finalize_tc])
    resp2.usage = MagicMock(prompt_tokens=200, completion_tokens=30, total_tokens=230)

    client.chat.completions.create.side_effect = [resp1, resp2]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = resolver.resolve("TestPlace")

    assert result.usage.prompt_tokens == 300
    assert result.usage.completion_tokens == 80
    assert result.usage.total_tokens == 380


@patch("geo_resolver.resolver.PlaceDB")
@patch("geo_resolver.resolver.OpenAI")
def test_resolve_async(mock_openai_cls, mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    search_tc = _make_tool_call("search_places", {"name": "TestPlace"}, "tc1")
    resp1 = make_chat_response(tool_calls=[search_tc])

    finalize_tc = _make_tool_call("finalize", {"geometry_id": "g1"}, "tc2")
    resp2 = make_chat_response(tool_calls=[finalize_tc])

    client.chat.completions.create.side_effect = [resp1, resp2]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = asyncio.run(resolver.resolve_async("TestPlace"))

    assert isinstance(result, ResolverResult)
    assert result.query == "TestPlace"
    assert not result.geometry.is_empty
