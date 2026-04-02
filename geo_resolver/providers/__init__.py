from .openai_adapter import OpenAIAdapter
from .base import ProviderAdapter, AdapterResponse, ToolCall

__all__ = [
    "ProviderAdapter", "AdapterResponse", "ToolCall",
    "OpenAIAdapter",
    "get_adapter",
]


_PROVIDER_MAP = {
    "openai": OpenAIAdapter,
}

# Lazy-load optional adapters to avoid import errors when SDKs aren't installed
_LAZY_PROVIDERS = {
    "anthropic": ("geo_resolver.providers.anthropic_adapter", "AnthropicAdapter"),
    "google": ("geo_resolver.providers.google_adapter", "GoogleAdapter"),
    "bedrock": ("geo_resolver.providers.bedrock_adapter", "BedrockAdapter"),
    "litellm": ("geo_resolver.providers.litellm_adapter", "LiteLLMAdapter"),
}


def _get_lazy_provider(name: str):
    """Import and cache a lazily-loaded provider adapter class."""
    if name in _LAZY_PROVIDERS:
        module_path, class_name = _LAZY_PROVIDERS[name]
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        _PROVIDER_MAP[name] = cls
        del _LAZY_PROVIDERS[name]
        return cls
    return None


def get_adapter(model: str, *, provider: str | None = None, client=None, **kwargs):
    """Create a provider adapter, auto-detecting provider from model name if needed."""
    if provider:
        cls = _PROVIDER_MAP.get(provider) or _get_lazy_provider(provider)
        if cls is None:
            available = sorted(set(list(_PROVIDER_MAP) + list(_LAZY_PROVIDERS)))
            raise ValueError(f"Unknown provider: {provider!r}. Available: {available}")
        return cls(model=model, client=client, **kwargs) if client else cls(model=model, **kwargs)

    # If a pre-built client is given, assume OpenAI-compatible
    if client is not None:
        return OpenAIAdapter(model=model, client=client, **kwargs)

    # Auto-detect from model name
    if model.startswith(("claude-", "anthropic/")):
        cls = _PROVIDER_MAP.get("anthropic") or _get_lazy_provider("anthropic")
        if cls:
            return cls(model=model, **kwargs)
    elif model.startswith(("gemini-", "google/")):
        cls = _PROVIDER_MAP.get("google") or _get_lazy_provider("google")
        if cls:
            return cls(model=model, **kwargs)
    elif model.startswith("bedrock/") or ("." in model and model.split(".")[0] in ("anthropic", "amazon", "meta", "cohere", "mistral")):
        cls = _PROVIDER_MAP.get("bedrock") or _get_lazy_provider("bedrock")
        if cls:
            return cls(model=model, **kwargs)

    # Default: OpenAI-compatible
    return OpenAIAdapter(model=model, **kwargs)
