import json
from unittest.mock import MagicMock, patch

import pytest


class TestBedrockAdapter:
    @patch("geo_resolver.providers.bedrock_adapter.boto3")
    def test_init(self, mock_boto3):
        from geo_resolver.providers.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")
        mock_boto3.Session.return_value.client.assert_called_once_with(
            "bedrock-runtime", region_name="us-east-1",
        )

    @patch("geo_resolver.providers.bedrock_adapter.boto3")
    def test_init_with_profile(self, mock_boto3):
        from geo_resolver.providers.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-west-2", profile="prod")
        mock_boto3.Session.assert_called_once_with(profile_name="prod")

    @patch("geo_resolver.providers.bedrock_adapter.boto3")
    def test_tool_call_response(self, mock_boto3):
        from geo_resolver.providers.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")

        mock_boto3.Session.return_value.client.return_value.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Searching"},
                        {"toolUse": {"toolUseId": "tu_123", "name": "search_places", "input": {"name": "Paris"}}},
                    ],
                },
            },
            "usage": {"inputTokens": 100, "outputTokens": 50},
        }

        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=[{"type": "function", "function": {"name": "search_places", "description": "x", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}}],
        )

        assert result.content == "Searching"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search_places"
        assert result.tool_calls[0].arguments == {"name": "Paris"}
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 50
        assert result.usage.total_tokens == 150

    @patch("geo_resolver.providers.bedrock_adapter.boto3")
    def test_text_only_response(self, mock_boto3):
        from geo_resolver.providers.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")

        mock_boto3.Session.return_value.client.return_value.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Done"}],
                },
            },
            "usage": {"inputTokens": 50, "outputTokens": 20},
        }

        result = adapter.chat_completion(messages=[{"role": "user", "content": "hi"}], tools=[])

        assert result.content == "Done"
        assert result.tool_calls is None
        assert result.usage.total_tokens == 70

    @patch("geo_resolver.providers.bedrock_adapter.boto3")
    def test_message_conversion(self, mock_boto3):
        """Verify system, assistant+tool_calls, and tool result messages convert correctly."""
        from geo_resolver.providers.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")

        mock_boto3.Session.return_value.client.return_value.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "find Paris"},
            {"role": "assistant", "content": "Searching", "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "search_places", "arguments": '{"name":"Paris"}'}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": '[{"name":"Paris"}]'},
        ]

        adapter.chat_completion(messages=messages, tools=[])

        call_kwargs = mock_boto3.Session.return_value.client.return_value.converse.call_args.kwargs
        assert call_kwargs["system"] == [{"text": "You are helpful"}]
        # Should have user, assistant (with toolUse), user (with toolResult)
        assert len(call_kwargs["messages"]) == 3
        assert call_kwargs["messages"][1]["content"][1]["toolUse"]["name"] == "search_places"
        assert call_kwargs["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "tc1"

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"boto3": None}):
            import importlib
            from geo_resolver.providers import bedrock_adapter
            importlib.reload(bedrock_adapter)
            with pytest.raises(ImportError, match="boto3"):
                bedrock_adapter.BedrockAdapter(model="anthropic.claude-sonnet-4-20250514-v1:0")
