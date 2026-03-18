"""geo-resolver: Natural language to GeoJSON boundary resolver.

Decompose geographic queries into structured lookups and spatial operations
against Overture Maps data using an LLM-driven agentic approach.
"""

from importlib.metadata import version, PackageNotFoundError
from .resolver import GeoResolver, LLMResolver
from .models import ResolverResult, TokenUsage

try:
    __version__ = version("geo-resolver")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = ["GeoResolver", "LLMResolver", "ResolverResult", "TokenUsage", "__version__"]
