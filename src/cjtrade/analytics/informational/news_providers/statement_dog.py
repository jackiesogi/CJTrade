from typing import List
from ._base import NewsInterface, News

class StatementDogProvider(NewsInterface):
    async def fetch_news_async(self) -> List[News]:
        pass
    
    def search_by_keyword(self, keyword: str) -> List[News]:
        pass
    
    def get_provider_name(self) -> str:
        return "StatementDog"