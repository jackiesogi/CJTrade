import asyncio
from enum import Enum
from typing import Any
from typing import List

from .news_providers._base import News
from .news_providers._base import NewsInterface

class NewsProviderType(Enum):
    """Supported news providers."""
    STATEMENT_DOG = "statement_dog"  # 財報狗
    NEWS_API = "news_api"            # NewsAPI
    MOCK = "mock"                    # Simulated News Source
    CNYES = "cnyes"                  # 鉅亨網

class NewsClient:
    """An unified API to interact with different news providers.

    Parameters
    ----------
    provider_type : NewsProviderType or str
        Provider to use; a string is converted with ``NewsProviderType(value)``.
    **config : Any
        Passed to the provider constructor (e.g. ``api_key`` for NewsAPI).

    Raises
    ------
    ValueError
        If the provider type is not supported.

    Warnings
    --------
    All providers except ``MOCK`` make network calls; results vary over time.
    """

    # TODO: provider_type should be union of str or Enum
    def __init__(self, provider_type: NewsProviderType, **config):
        if isinstance(provider_type, str):
            provider_type = NewsProviderType(provider_type)
        self.provider_type = provider_type
        self.provider = self._create_provider(provider_type, **config)

    def _create_provider(self, provider_type: NewsProviderType, **config) -> NewsInterface:
        if provider_type == NewsProviderType.STATEMENT_DOG:
            from .news_providers.statement_dog import StatementDogProvider
            return StatementDogProvider(**config)
        elif provider_type == NewsProviderType.NEWS_API:
            from .news_providers.news_api import NewsAPIProvider
            return NewsAPIProvider(**config)
        elif provider_type == NewsProviderType.CNYES:
            from .news_providers.cnyes import CnyesProvider
            return CnyesProvider(**config)
        elif provider_type == NewsProviderType.MOCK:
            from .news_providers.mock import MockNewsProvider
            return MockNewsProvider(**config)
        else:
            raise ValueError(f"Unsupported news provider type: {provider_type}")

    async def fetch_headline_news_async(self, n: int = 10) -> List[News]:
        """Fetch up to `n` headline news items asynchronously from the provider."""
        return await self.provider.fetch_headline_news_async(n=n)

    def fetch_headline_news(self, n: int = 10) -> List[News]:
        """Fetch up to `n` headline news items from the provider (blocking)."""
        return self.provider.fetch_headline_news(n=n)

    def search_by_keyword(self, keyword: str, n: int = 10) -> List[News]:
        """Search the provider for up to `n` news items matching `keyword`."""
        return self.provider.search_by_keyword(keyword, n=n)

    def get_provider_name(self) -> str:
        """Return the provider name."""
        return self.provider.get_provider_name()

    @property
    def current_provider_type(self) -> NewsProviderType:
        """The provider type this client was created with."""
        return self.provider_type
