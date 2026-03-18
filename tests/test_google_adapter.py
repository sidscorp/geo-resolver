from unittest.mock import MagicMock, patch

import pytest


class TestGoogleAdapter:
    @patch("geo_resolver.providers.google_adapter.genai")
    def test_init(self, mock_genai):
        from geo_resolver.providers.google_adapter import GoogleAdapter
        adapter = GoogleAdapter(model="gemini-2.5-flash", api_key="test-key")
        mock_genai.Client.assert_called_once_with(api_key="test-key")

    @patch("geo_resolver.providers.google_adapter.genai")
    def test_tool_call_response(self, mock_genai):
        from geo_resolver.providers.google_adapter import GoogleAdapter
        adapter = GoogleAdapter(model="gemini-2.5-flash", api_key="test")

        fc_part = MagicMock()
        fc_part.function_call = MagicMock()
        fc_part.function_call.name = "search_places"
        fc_part.function_call.args = {"name": "Paris"}
        fc_part.function_call.id = "fc_123"
        fc_part.text = None

        text_part = MagicMock()
        text_part.function_call = None
        text_part.text = "Searching"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [text_part, fc_part]

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata = MagicMock(
            prompt_token_count=80,
            candidates_token_count=40,
            total_token_count=120,
        )

        mock_genai.Client.return_value.models.generate_content.return_value = mock_resp

        result = adapter.chat_completion(
            messages=[{"role": "user", "content": "Paris"}],
            tools=[{"type": "function", "function": {"name": "search_places", "description": "x", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}}],
        )

        assert result.content == "Searching"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search_places"
        assert result.tool_calls[0].arguments == {"name": "Paris"}
        assert result.usage.total_tokens == 120

    @patch("geo_resolver.providers.google_adapter.genai")
    def test_text_only_response(self, mock_genai):
        from geo_resolver.providers.google_adapter import GoogleAdapter
        adapter = GoogleAdapter(model="gemini-2.5-flash", api_key="test")

        text_part = MagicMock()
        text_part.function_call = None
        text_part.text = "The answer is 42"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [text_part]

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata = MagicMock(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15,
        )

        mock_genai.Client.return_value.models.generate_content.return_value = mock_resp

        result = adapter.chat_completion(messages=[{"role": "user", "content": "hi"}], tools=[])

        assert result.content == "The answer is 42"
        assert result.tool_calls is None

    @patch("geo_resolver.providers.google_adapter.genai")
    def test_no_usage_metadata(self, mock_genai):
        from geo_resolver.providers.google_adapter import GoogleAdapter
        adapter = GoogleAdapter(model="gemini-2.5-flash", api_key="test")

        text_part = MagicMock()
        text_part.function_call = None
        text_part.text = "ok"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [text_part]

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata = None

        mock_genai.Client.return_value.models.generate_content.return_value = mock_resp

        result = adapter.chat_completion(messages=[], tools=[])
        assert result.usage.total_tokens == 0

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"google": None, "google.genai": None}):
            import importlib
            from geo_resolver.providers import google_adapter
            importlib.reload(google_adapter)
            with pytest.raises(ImportError, match="google-genai"):
                google_adapter.GoogleAdapter(model="gemini-2.5-flash", api_key="test")
