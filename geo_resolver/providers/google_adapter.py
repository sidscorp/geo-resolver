from .base import ProviderAdapter, AdapterResponse, ToolCall
from ..models import TokenUsage

try:
    from google import genai
except ImportError:
    genai = None


class GoogleAdapter(ProviderAdapter):
    """Adapter for Google Generative AI (Gemini) SDK."""

    def __init__(self, model: str, *, api_key=None, **kwargs):
        super().__init__(model=model)
        if genai is None:
            raise ImportError(
                "Google provider requires the 'google-genai' package. "
                "Install it with: pip install geo-resolver[google]"
            )
        self.client = genai.Client(api_key=api_key)

    def _convert_tools(self, tools: list[dict]) -> list:
        """Convert OpenAI-format tools to Google function declarations."""
        declarations = []
        for tool in tools:
            fn = tool.get("function", {})
            declarations.append(genai.types.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=fn.get("parameters"),
            ))
        return [genai.types.Tool(function_declarations=declarations)]

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list]:
        """Convert OpenAI-format messages to Google Content format.

        Returns (system_instruction, contents).
        """
        system = None
        contents = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system = msg["content"]

            elif role == "user":
                contents.append(genai.types.Content(
                    role="user",
                    parts=[genai.types.Part.from_text(text=msg["content"])],
                ))

            elif role == "assistant":
                parts = []
                if msg.get("content"):
                    parts.append(genai.types.Part.from_text(text=msg["content"]))
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        import json
                        args = json.loads(args)
                    parts.append(genai.types.Part.from_function_call(
                        name=fn["name"], args=args,
                    ))
                contents.append(genai.types.Content(role="model", parts=parts))

            elif role == "tool":
                import json as json_mod
                try:
                    result_data = json_mod.loads(msg["content"])
                except (json_mod.JSONDecodeError, TypeError):
                    result_data = {"result": msg["content"]}
                parts = [genai.types.Part.from_function_response(
                    name="tool_response",
                    response=result_data if isinstance(result_data, dict) else {"result": result_data},
                )]
                contents.append(genai.types.Content(role="user", parts=parts))

        return system, contents

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        system, contents = self._convert_messages(messages)

        config_kwargs = {}
        if system:
            config_kwargs["system_instruction"] = system
        if tools:
            config_kwargs["tools"] = self._convert_tools(tools)

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=genai.types.GenerateContentConfig(**config_kwargs),
        )

        content_text = None
        tool_calls = []

        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=getattr(fc, "id", None) or f"fc_{fc.name}",
                    name=fc.name,
                    arguments=dict(fc.args) if fc.args else {},
                ))
            elif part.text:
                content_text = part.text

        usage = TokenUsage()
        if response.usage_metadata:
            um = response.usage_metadata
            usage = TokenUsage(
                prompt_tokens=um.prompt_token_count,
                completion_tokens=um.candidates_token_count,
                total_tokens=um.total_token_count,
            )

        return AdapterResponse(
            content=content_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )
