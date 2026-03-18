import json

from .base import ProviderAdapter, AdapterResponse, ToolCall
from ..models import TokenUsage

try:
    import litellm
except ImportError:
    litellm = None


class LiteLLMAdapter(ProviderAdapter):
    """Adapter for LiteLLM (universal LLM proxy)."""

    def __init__(self, model: str, *, api_key=None, **kwargs):
        super().__init__(model=model)
        if litellm is None:
            raise ImportError(
                "LiteLLM provider requires the 'litellm' package. "
                "Install it with: pip install geo-resolver[litellm]"
            )
        self.api_key = api_key

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        kwargs = dict(model=self.model, messages=messages)
        if tools:
            kwargs["tools"] = tools
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = litellm.completion(**kwargs)

        choice = response.choices[0]
        msg = choice.message

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

        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return AdapterResponse(content=msg.content, tool_calls=tool_calls, usage=usage)
