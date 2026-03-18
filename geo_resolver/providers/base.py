from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import TokenUsage


@dataclass
class ToolCall:
    """A single tool call from the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class AdapterResponse:
    """Normalized response from any LLM provider."""
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: TokenUsage


class ProviderAdapter(ABC):
    """Base class for LLM provider adapters."""

    def __init__(self, model: str, **kwargs):
        self.model = model

    @abstractmethod
    def chat_completion(self, messages: list[dict], tools: list[dict]) -> AdapterResponse:
        """Send messages and tools to the LLM, return normalized response."""
        ...
