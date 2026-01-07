from abc import ABC, abstractmethod
from typing import Any, List

class News:
    def __init__(self, title: str, content: str):
        self.title = title
        self.content = content

class NewsInterface(ABC):
    """
    An unified interface for different news providers.
    All news provider implementations must inherit from
    this class and implement all abstract methods.
    """
    def __init__(self, **config: Any):
        self.config = config

    @abstractmethod
    async def fetch_headline_news_async(self, n: int = 10) -> List[News]:
        """Fetch latest news asynchronously."""
        pass

    @abstractmethod
    def fetch_headline_news(self, n: int = 10) -> List[News]:
        """Fetch latest news. (blocking call)"""
        pass
    
    @abstractmethod
    def search_by_keyword(self, keyword: str, n: int = 10) -> List[News]:
        """Search news by keyword."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider name."""
        pass