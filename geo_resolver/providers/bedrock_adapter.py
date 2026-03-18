import json

from .base import ProviderAdapter, AdapterResponse, ToolCall
from ..models import TokenUsage

try:
    import boto3
except ImportError:
    boto3 = None


class BedrockAdapter(ProviderAdapter):
    """Adapter for AWS Bedrock Converse API."""

    def __init__(self, model: str, *, region=None, profile=None, **kwargs):
        super().__init__(model=model)
        if boto3 is None:
            raise ImportError(
                "Bedrock provider requires the 'boto3' package. "
                "Install it with: pip install geo-resolver[bedrock]"
            )
        session = boto3.Session(profile_name=profile)
        self.client = session.client("bedrock-runtime", region_name=region)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tools to Bedrock toolSpec format."""
        result = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append({
                "toolSpec": {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "inputSchema": {
                        "json": fn.get("parameters", {"type": "object", "properties": {}}),
                    },
                },
            })
        return result

    def _convert_messages(self, messages: list[dict]) -> tuple[list[dict] | None, list[dict]]:
        """Convert OpenAI-format messages to Bedrock format.

        Returns (system, messages).
        """
        system = None
        converted = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system = [{"text": msg["content"]}]

            elif role == "user":
                converted.append({
                    "role": "user",
                    "content": [{"text": msg["content"]}],
                })

            elif role == "assistant":
                content = []
                if msg.get("content"):
                    content.append({"text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        args = json.loads(args)
                    content.append({
                        "toolUse": {
                            "toolUseId": tc["id"],
                            "name": fn["name"],
                            "input": args,
                        },
                    })
                converted.append({"role": "assistant", "content": content})

            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "toolResult": {
                            "toolUseId": msg["tool_call_id"],
                            "content": [{"text": msg["content"]}],
                        },
                    }],
                })

        return system, converted

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        system, converted_messages = self._convert_messages(messages)

        kwargs = dict(
            modelId=self.model,
            messages=converted_messages,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["toolConfig"] = {"tools": self._convert_tools(tools)}

        response = self.client.converse(**kwargs)

        content_text = None
        tool_calls = []

        for block in response["output"]["message"]["content"]:
            if "text" in block:
                content_text = block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(
                    id=tu["toolUseId"],
                    name=tu["name"],
                    arguments=tu.get("input", {}),
                ))

        usage_data = response.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("inputTokens", 0),
            completion_tokens=usage_data.get("outputTokens", 0),
            total_tokens=usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0),
        )

        return AdapterResponse(
            content=content_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )
