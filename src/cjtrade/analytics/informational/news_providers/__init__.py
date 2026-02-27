# News providers module
from ._base import News
from ._base import NewsInterface
from .mock import MockNewsProvider
from .news_api import NewsAPIProvider
from .statement_dog import StatementDogProvider

__all__ = [
    'NewsInterface',
    'News',
    'StatementDogProvider',
    'NewsAPIProvider',
    'MockNewsProvider'
]
