import json

from .base import ProviderAdapter, AdapterResponse, ToolCall
from ..models import TokenUsage

try:
    import anthropic
except ImportError:
    anthropic = None


class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic's native Messages API."""

    def __init__(self, model: str, *, api_key=None, **kwargs):
        super().__init__(model=model)
        if anthropic is None:
            raise ImportError(
                "Anthropic provider requires the 'anthropic' package. "
                "Install it with: pip install geo-resolver[anthropic]"
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tools to Anthropic format."""
        result = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns (system_prompt, messages) where system is extracted separately.
        """
        system = ""
        converted = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system = msg["content"]

            elif role == "user":
                converted.append({"role": "user", "content": msg["content"]})

            elif role == "assistant":
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        args = json.loads(args)
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": fn["name"],
                        "input": args,
                    })
                converted.append({"role": "assistant", "content": content})

            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg["tool_call_id"],
                        "content": msg["content"],
                    }],
                })

        return system, converted

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        system, converted_messages = self._convert_messages(messages)

        kwargs = dict(
            model=self.model,
            messages=converted_messages,
            max_tokens=4096,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = self.client.messages.create(**kwargs)

        content_text = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        usage = TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )

        return AdapterResponse(
            content=content_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )
