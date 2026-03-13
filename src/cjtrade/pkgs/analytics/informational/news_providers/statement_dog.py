from typing import List

from ._base import News
from ._base import NewsInterface

class StatementDogProvider(NewsInterface):
    async def fetch_headline_news_async(self) -> List[News]:
        pass

    def search_by_keyword(self, keyword: str) -> List[News]:
        pass

    def get_provider_name(self) -> str:
        return "StatementDog"
