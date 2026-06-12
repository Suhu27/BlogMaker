"""
Search provider abstraction for BlogMaker.

Defines the abstract interface and factory for search providers.
Currently implements GeminiSearchProvider.
Future providers (Tavily, Serper, etc.) can be added by subclassing BaseSearchProvider.
"""

from abc import ABC, abstractmethod

from src.config import AppConfig
from src.logger import get_logger
from src.models import Source

logger = get_logger("search_providers")


class BaseSearchProvider(ABC):
    """Abstract base class for search providers."""

    @abstractmethod
    def search(self, query: str) -> tuple[str, list[Source]]:
        """
        Search for a topic and return research text with sources.

        Args:
            query: The search query / topic.

        Returns:
            Tuple of (research_text, list_of_sources).
        """
        ...

    @property
    @abstractmethod
    def input_tokens(self) -> int:
        """Total input tokens consumed."""
        ...

    @property
    @abstractmethod
    def output_tokens(self) -> int:
        """Total output tokens consumed."""
        ...


class GeminiSearchProvider(BaseSearchProvider):
    """Search provider using Gemini with Google Search grounding."""

    def __init__(self, config: AppConfig) -> None:
        from src.researcher import GeminiResearcher
        self._researcher = GeminiResearcher(config)

    def search(self, query: str) -> tuple[str, list[Source]]:
        return self._researcher.research_topic(query)

    @property
    def input_tokens(self) -> int:
        return self._researcher.input_tokens

    @property
    def output_tokens(self) -> int:
        return self._researcher.output_tokens


def create_search_provider(config: AppConfig) -> BaseSearchProvider:
    """
    Factory function to create a search provider based on config.

    Args:
        config: Application configuration.

    Returns:
        A search provider instance.

    Raises:
        ValueError: If the configured provider is not supported.
    """
    provider_name = config.search_provider.lower()

    if provider_name == "gemini":
        return GeminiSearchProvider(config)

    # Future providers can be added here:
    # if provider_name == "tavily":
    #     return TavilySearchProvider(config)
    # if provider_name == "serper":
    #     return SerperSearchProvider(config)

    raise ValueError(
        f"Unknown search provider: '{provider_name}'. "
        f"Supported providers: gemini"
    )
