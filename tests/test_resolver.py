import os
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from geo_resolver.resolver import GeoResolver
from geo_resolver.models import ResolverResult, TokenUsage
from tests.conftest import make_adapter_response


def _make_adapter_mock(*responses):
    """Create a mock adapter with pre-set responses."""
    adapter = MagicMock()
    adapter.model = "test-model"
    adapter.chat_completion.side_effect = list(responses)
    return adapter


def _search_then_finalize():
    """Standard 2-turn flow: search_places -> finalize."""
    resp1 = make_adapter_response(
        tool_calls=[{"id": "tc1", "name": "search_places", "arguments": {"name": "TestPlace"}}],
    )
    resp2 = make_adapter_response(
        tool_calls=[{"id": "tc2", "name": "finalize", "arguments": {"geometry_id": "g1"}}],
    )
    return resp1, resp2


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_simple(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    adapter = _make_adapter_mock(*_search_then_finalize())

    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    result = resolver.resolve("TestPlace")

    assert isinstance(result, ResolverResult)
    assert result.query == "TestPlace"
    assert not result.geometry.is_empty


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_empty_query_raises(mock_db_cls):
    mock_db_cls.return_value = MagicMock()
    adapter = MagicMock()
    adapter.model = "test-model"
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)

    with pytest.raises(ValueError, match="non-empty"):
        resolver.resolve("")


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_long_query_raises(mock_db_cls):
    mock_db_cls.return_value = MagicMock()
    adapter = MagicMock()
    adapter.model = "test-model"
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)

    with pytest.raises(ValueError, match="2000"):
        resolver.resolve("x" * 2001)


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_no_geometry_raises(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    from geo_resolver.models import Place
    mock_db.search_places.return_value = [
        Place(id="x", name="NoGeom", subtype="locality", country=None, region=None, geometry=None)
    ]

    resp1 = make_adapter_response(
        tool_calls=[{"id": "tc1", "name": "search_places", "arguments": {"name": "NoGeom"}}],
    )
    resp2 = make_adapter_response(content="I can't find geometry")
    resp3 = make_adapter_response(content="Still nothing")

    adapter = _make_adapter_mock(resp1, resp2, resp3)
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)

    with pytest.raises(RuntimeError, match="no matching geometries"):
        resolver.resolve("NoGeom")


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_fallback_to_largest(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db

    resp1 = make_adapter_response(
        tool_calls=[{"id": "tc1", "name": "search_places", "arguments": {"name": "TestPlace"}}],
    )
    resp2 = make_adapter_response(content="Thinking...")
    resp3 = make_adapter_response(content="Still thinking...")

    adapter = _make_adapter_mock(resp1, resp2, resp3)
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    result = resolver.resolve("TestPlace")

    assert isinstance(result, ResolverResult)
    assert not result.geometry.is_empty


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_on_step_callback(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    adapter = _make_adapter_mock(*_search_then_finalize())

    steps = []
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    resolver.resolve("TestPlace", on_step=lambda s: steps.append(s))

    assert len(steps) >= 2
    assert any(s.get("tool") == "search_places" for s in steps)
    assert any(s.get("tool") == "finalize" for s in steps)


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_max_iterations(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db

    resp = make_adapter_response(
        tool_calls=[{"id": "tc1", "name": "search_places", "arguments": {"name": "TestPlace"}}],
    )

    adapter = _make_adapter_mock(resp, resp, resp)
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    result = resolver.resolve("TestPlace", max_iterations=2)

    assert isinstance(result, ResolverResult)
    assert adapter.chat_completion.call_count == 2


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_tracks_usage(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db

    resp1 = make_adapter_response(
        tool_calls=[{"id": "tc1", "name": "search_places", "arguments": {"name": "TestPlace"}}],
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )
    resp2 = make_adapter_response(
        tool_calls=[{"id": "tc2", "name": "finalize", "arguments": {"geometry_id": "g1"}}],
        usage=TokenUsage(prompt_tokens=200, completion_tokens=30, total_tokens=230),
    )

    adapter = _make_adapter_mock(resp1, resp2)
    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    result = resolver.resolve("TestPlace")

    assert result.usage.prompt_tokens == 300
    assert result.usage.completion_tokens == 80
    assert result.usage.total_tokens == 380


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_async(mock_db_cls, mock_db):
    mock_db_cls.return_value = mock_db
    adapter = _make_adapter_mock(*_search_then_finalize())

    resolver = GeoResolver(data_dir="/fake", model="test-model", adapter=adapter)
    result = asyncio.run(resolver.resolve_async("TestPlace"))

    assert isinstance(result, ResolverResult)
    assert result.query == "TestPlace"
    assert not result.geometry.is_empty


# --- Backwards compatibility: client= still works ---

@patch("geo_resolver.resolver.PlaceDB")
@patch("openai.OpenAI")
def test_backwards_compat_client(mock_openai_cls, mock_db_cls, mock_db):
    """Passing client= wraps it in OpenAIAdapter transparently."""
    mock_db_cls.return_value = mock_db
    client = MagicMock()

    tc = MagicMock()
    tc.id = "tc1"
    tc.function.name = "search_places"
    tc.function.arguments = json.dumps({"name": "TestPlace"})

    message = MagicMock()
    message.content = None
    message.tool_calls = [tc]
    choice = MagicMock()
    choice.message = message
    resp1 = MagicMock()
    resp1.choices = [choice]
    resp1.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    tc2 = MagicMock()
    tc2.id = "tc2"
    tc2.function.name = "finalize"
    tc2.function.arguments = json.dumps({"geometry_id": "g1"})
    message2 = MagicMock()
    message2.content = None
    message2.tool_calls = [tc2]
    choice2 = MagicMock()
    choice2.message = message2
    resp2 = MagicMock()
    resp2.choices = [choice2]
    resp2.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    client.chat.completions.create.side_effect = [resp1, resp2]

    resolver = GeoResolver(data_dir="/fake", model="test-model", client=client)
    result = resolver.resolve("TestPlace")

    assert isinstance(result, ResolverResult)


# --- Mode routing tests ---

@patch("geo_resolver.direct_resolver.DirectResolver")
@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_mode_direct(mock_db_cls, mock_direct_cls, mock_db):
    mock_db_cls.return_value = mock_db

    fake_result = ResolverResult(
        query="TestPlace",
        geometry=mock_db.search_places.return_value[0].geometry,
        steps=[],
    )
    mock_direct_cls.return_value.resolve.return_value = fake_result

    resolver = GeoResolver(data_dir="/fake", mode="direct")
    result = resolver.resolve("TestPlace", mode="direct")

    assert isinstance(result, ResolverResult)
    mock_direct_cls.return_value.resolve.assert_called_once()


@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_mode_unknown_raises(mock_db_cls):
    mock_db_cls.return_value = MagicMock()
    resolver = GeoResolver(data_dir="/fake", mode="llm")

    with pytest.raises(ValueError, match="Unknown mode"):
        resolver.resolve("TestPlace", mode="bogus")


@patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "GEO_RESOLVER_MODEL"}, clear=True)
@patch("geo_resolver.direct_resolver.DirectResolver")
@patch("geo_resolver.resolver.PlaceDB")
def test_resolve_without_model_direct_still_works(mock_db_cls, mock_direct_cls, mock_db):
    mock_db_cls.return_value = mock_db

    fake_result = ResolverResult(
        query="TestPlace",
        geometry=mock_db.search_places.return_value[0].geometry,
        steps=[],
    )
    mock_direct_cls.return_value.resolve.return_value = fake_result

    resolver = GeoResolver(data_dir="/fake", mode="direct")
    assert resolver._llm is None

    result = resolver.resolve("TestPlace", mode="direct")
    assert isinstance(result, ResolverResult)
    mock_direct_cls.return_value.resolve.assert_called_once()
