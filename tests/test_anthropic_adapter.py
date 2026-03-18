import json
from unittest.mock import MagicMock, patch

import pytest


class TestAnthropicAdapter:
    @patch("geo_resolver.providers.anthropic_adapter.anthropic")
    def test_init(self, mock_anthropic):
        from geo_resolver.providers.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="sk-ant-test")
        mock_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-test")

    @patch("geo_resolver.providers.anthropic_adapter.anthropic")
    def test_tool_conversion(self, mock_anthropic):
        """OpenAI-format tools are converted to Anthropic format."""
        from geo_resolver.providers.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test")

        openai_tools = [{
            "type": "function",
            "function": {
                "name": "search_places",
                "description": "Search for places",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }]

        mock_resp = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "thinking"
        mock_resp.content = [text_block]
        mock_resp.stop_reason = "end_turn"
        mock_resp.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_resp

        adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=openai_tools,
        )

        call_kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert tools[0]["name"] == "search_places"
        assert tools[0]["input_schema"]["type"] == "object"

    @patch("geo_resolver.providers.anthropic_adapter.anthropic")
    def test_tool_call_response(self, mock_anthropic):
        from geo_resolver.providers.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test")

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me search"

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_123"
        tool_block.name = "search_places"
        tool_block.input = {"name": "Paris"}

        mock_resp = MagicMock()
        mock_resp.content = [text_block, tool_block]
        mock_resp.stop_reason = "tool_use"
        mock_resp.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_resp

        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=[{"type": "function", "function": {"name": "search_places", "description": "x", "parameters": {}}}],
        )

        assert result.content == "Let me search"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "toolu_123"
        assert result.tool_calls[0].name == "search_places"
        assert result.tool_calls[0].arguments == {"name": "Paris"}
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 50
        assert result.usage.total_tokens == 150

    @patch("geo_resolver.providers.anthropic_adapter.anthropic")
    def test_message_conversion(self, mock_anthropic):
        """Tool result messages are converted from OpenAI to Anthropic format."""
        from geo_resolver.providers.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test")

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "done"
        mock_resp = MagicMock()
        mock_resp.content = [text_block]
        mock_resp.stop_reason = "end_turn"
        mock_resp.usage = MagicMock(input_tokens=50, output_tokens=20)
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_resp

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "find Paris"},
            {"role": "assistant", "content": "Let me search", "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "search_places", "arguments": '{"name":"Paris"}'}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": '[{"name":"Paris"}]'},
        ]

        adapter.chat_completion(messages=messages, tools=[])

        call_kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        assert all(m["role"] != "system" for m in call_kwargs["messages"])
        # Assistant message should have content blocks
        assistant_msg = call_kwargs["messages"][1]
        assert assistant_msg["role"] == "assistant"
        # Tool result should be role=user with tool_result content
        tool_msg = call_kwargs["messages"][2]
        assert tool_msg["role"] == "user"
        assert tool_msg["content"][0]["type"] == "tool_result"

    @patch("geo_resolver.providers.anthropic_adapter.anthropic")
    def test_text_only_response(self, mock_anthropic):
        from geo_resolver.providers.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test")

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "The answer is 42"
        mock_resp = MagicMock()
        mock_resp.content = [text_block]
        mock_resp.usage = MagicMock(input_tokens=10, output_tokens=5)
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_resp

        result = adapter.chat_completion(messages=[{"role": "user", "content": "hi"}], tools=[])
        assert result.content == "The answer is 42"
        assert result.tool_calls is None

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"anthropic": None}):
            import importlib
            from geo_resolver.providers import anthropic_adapter
            importlib.reload(anthropic_adapter)
            with pytest.raises(ImportError, match="anthropic"):
                anthropic_adapter.AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test")
