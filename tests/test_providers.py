from geo_resolver.providers.base import ProviderAdapter, AdapterResponse, ToolCall
from geo_resolver.models import TokenUsage
import pytest


def test_tool_call_dataclass():
    tc = ToolCall(id="tc1", name="search_places", arguments={"name": "Paris"})
    assert tc.id == "tc1"
    assert tc.name == "search_places"
    assert tc.arguments == {"name": "Paris"}


def test_adapter_response_dataclass():
    resp = AdapterResponse(
        content="thinking",
        tool_calls=[ToolCall(id="tc1", name="search_places", arguments={"name": "Paris"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert resp.content == "thinking"
    assert len(resp.tool_calls) == 1
    assert resp.usage.total_tokens == 15


def test_adapter_response_no_tools():
    resp = AdapterResponse(content="done", tool_calls=None, usage=TokenUsage())
    assert resp.tool_calls is None


def test_provider_adapter_is_abstract():
    with pytest.raises(TypeError):
        ProviderAdapter(model="test")
