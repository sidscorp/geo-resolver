import json
from unittest.mock import MagicMock, patch

import pytest


class TestLiteLLMAdapter:
    @patch("geo_resolver.providers.litellm_adapter.litellm")
    def test_tool_call_response(self, mock_litellm):
        from geo_resolver.providers.litellm_adapter import LiteLLMAdapter
        adapter = LiteLLMAdapter(model="anthropic/claude-sonnet-4-20250514", api_key="test")

        tc = MagicMock()
        tc.id = "call_456"
        tc.function.name = "search_places"
        tc.function.arguments = json.dumps({"name": "Paris"})

        message = MagicMock()
        message.content = "Searching"
        message.tool_calls = [tc]

        choice = MagicMock()
        choice.message = message

        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage = MagicMock(prompt_tokens=80, completion_tokens=40, total_tokens=120)

        mock_litellm.completion.return_value = mock_resp

        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=[{"type": "function", "function": {"name": "search_places"}}],
        )

        assert result.content == "Searching"
        assert result.tool_calls[0].name == "search_places"
        assert result.tool_calls[0].arguments == {"name": "Paris"}
        assert result.usage.total_tokens == 120
        mock_litellm.completion.assert_called_once()

    @patch("geo_resolver.providers.litellm_adapter.litellm")
    def test_text_only(self, mock_litellm):
        from geo_resolver.providers.litellm_adapter import LiteLLMAdapter
        adapter = LiteLLMAdapter(model="anthropic/claude-sonnet-4-20250514")

        message = MagicMock()
        message.content = "Done"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage = None
        mock_litellm.completion.return_value = mock_resp

        result = adapter.chat_completion(messages=[], tools=[])
        assert result.content == "Done"
        assert result.tool_calls is None
        assert result.usage.total_tokens == 0

    @patch("geo_resolver.providers.litellm_adapter.litellm")
    def test_api_key_passed(self, mock_litellm):
        from geo_resolver.providers.litellm_adapter import LiteLLMAdapter
        adapter = LiteLLMAdapter(model="openai/gpt-4o", api_key="sk-test")

        message = MagicMock()
        message.content = "ok"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage = None
        mock_litellm.completion.return_value = mock_resp

        adapter.chat_completion(messages=[{"role": "user", "content": "hi"}], tools=[])

        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-test"

    @patch("geo_resolver.providers.litellm_adapter.litellm")
    def test_no_api_key(self, mock_litellm):
        from geo_resolver.providers.litellm_adapter import LiteLLMAdapter
        adapter = LiteLLMAdapter(model="openai/gpt-4o")

        message = MagicMock()
        message.content = "ok"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        mock_resp = MagicMock()
        mock_resp.choices = [choice]
        mock_resp.usage = None
        mock_litellm.completion.return_value = mock_resp

        adapter.chat_completion(messages=[], tools=[])

        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert "api_key" not in call_kwargs

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"litellm": None}):
            import importlib
            from geo_resolver.providers import litellm_adapter
            importlib.reload(litellm_adapter)
            with pytest.raises(ImportError, match="litellm"):
                litellm_adapter.LiteLLMAdapter(model="anthropic/claude-sonnet-4-20250514")
