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


import json
from unittest.mock import MagicMock, patch


class TestOpenAIAdapter:
    def _make_adapter(self, client=None, model="gpt-4o"):
        from geo_resolver.providers.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(model=model, client=client, api_key="test-key")

    def test_init_with_client(self):
        client = MagicMock()
        adapter = self._make_adapter(client=client)
        assert adapter.model == "gpt-4o"

    @patch("openai.OpenAI")
    def test_init_creates_client(self, mock_cls):
        from geo_resolver.providers.openai_adapter import OpenAIAdapter
        adapter = OpenAIAdapter(model="gpt-4o", api_key="sk-test", base_url="http://localhost")
        mock_cls.assert_called_once_with(api_key="sk-test", base_url="http://localhost")

    def test_chat_completion_with_tool_calls(self):
        client = MagicMock()

        tc = MagicMock()
        tc.id = "call_123"
        tc.function.name = "search_places"
        tc.function.arguments = json.dumps({"name": "Paris"})

        message = MagicMock()
        message.content = "Let me search"
        message.tool_calls = [tc]

        choice = MagicMock()
        choice.message = message

        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)

        client.chat.completions.create.return_value = response

        adapter = self._make_adapter(client=client)
        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=[{"type": "function", "function": {"name": "search_places"}}],
        )

        assert result.content == "Let me search"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].name == "search_places"
        assert result.tool_calls[0].arguments == {"name": "Paris"}
        assert result.usage.total_tokens == 150

    def test_chat_completion_text_only(self):
        client = MagicMock()

        message = MagicMock()
        message.content = "I found it"
        message.tool_calls = None

        choice = MagicMock()
        choice.message = message

        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(prompt_tokens=50, completion_tokens=20, total_tokens=70)

        client.chat.completions.create.return_value = response

        adapter = self._make_adapter(client=client)
        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )

        assert result.content == "I found it"
        assert result.tool_calls is None
        assert result.usage.prompt_tokens == 50

    def test_chat_completion_no_usage(self):
        client = MagicMock()

        message = MagicMock()
        message.content = "ok"
        message.tool_calls = None

        choice = MagicMock()
        choice.message = message

        response = MagicMock()
        response.choices = [choice]
        response.usage = None

        client.chat.completions.create.return_value = response

        adapter = self._make_adapter(client=client)
        result = adapter.chat_completion(messages=[], tools=[])

        assert result.usage.total_tokens == 0

    def test_messages_pass_through(self):
        """OpenAI messages pass through unchanged."""
        client = MagicMock()

        message = MagicMock()
        message.content = "done"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = None
        client.chat.completions.create.return_value = response

        adapter = self._make_adapter(client=client)
        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "find Paris"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "[]"},
        ]
        adapter.chat_completion(messages=messages, tools=[])

        call_args = client.chat.completions.create.call_args
        assert call_args.kwargs["messages"] == messages
