import json

from .base import ProviderAdapter, AdapterResponse, ToolCall
from ..models import TokenUsage


class OpenAIAdapter(ProviderAdapter):
    """Adapter for OpenAI and any OpenAI-compatible API (Azure, Ollama, OpenRouter)."""

    def __init__(self, model: str, *, client=None, api_key=None, base_url=None, **kwargs):
        super().__init__(model=model)
        if client is not None:
            self.client = client
        else:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        kwargs = dict(model=self.model, messages=messages)
        if tools:
            kwargs["tools"] = tools
        response = self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        msg = choice.message

        # Parse tool calls
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]

        # Parse usage
        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return AdapterResponse(content=msg.content, tool_calls=tool_calls, usage=usage)
