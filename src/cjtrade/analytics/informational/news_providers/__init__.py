# News providers module
from ._base import NewsInterface, News
from .statement_dog import StatementDogProvider
from .news_api import NewsAPIProvider
from .mock import MockNewsProvider

__all__ = [
    'NewsInterface',
    'News', 
    'StatementDogProvider',
    'NewsAPIProvider',
    'MockNewsProvider'
]