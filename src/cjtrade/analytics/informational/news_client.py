import asyncio
from enum import Enum
from typing import Any, List
from .news_providers._base import NewsInterface, News

class NewsProviderType(Enum):
    STATEMENT_DOG = "statement_dog"  # 財報狗
    NEWS_API = "news_api"            # NewsAPI
    MOCK = "mock"                    # Simulated News Source

class NewsClient:
    """An unified API to interact with different news providers."""

    def __init__(self, provider_type: NewsProviderType, **config):
        self.provider_type = provider_type
        self.provider = self._create_provider(provider_type, **config)

    def _create_provider(self, provider_type: NewsProviderType, **config) -> NewsInterface:
        if provider_type == NewsProviderType.STATEMENT_DOG:
            from .news_providers.statement_dog import StatementDogProvider
            return StatementDogProvider(**config)
        elif provider_type == NewsProviderType.NEWS_API:
            from .news_providers.news_api import NewsAPIProvider
            return NewsAPIProvider(**config)
        elif provider_type == NewsProviderType.MOCK:
            from .news_providers.mock import MockNewsProvider
            return MockNewsProvider(**config)
        else:
            raise ValueError(f"Unsupported news provider type: {provider_type}")

    async def fetch_news_async(self) -> List[News]:
        return await self.provider.fetch_news_async()

    def fetch_news(self) -> List[News]:
        return self.provider.fetch_news()

    def search_by_keyword(self, keyword: str) -> List[News]:
        return self.provider.search_by_keyword(keyword)

    def get_provider_name(self) -> str:
        return self.provider.get_provider_name()

    @property
    def current_provider_type(self) -> NewsProviderType:
        return self.provider_type