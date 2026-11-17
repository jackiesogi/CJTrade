from typing import List

from ._base import News
from ._base import NewsInterface

class StatementDogProvider(NewsInterface):
    """Placeholder provider for StatementDog (財報狗).

    Warnings
    --------
    Not implemented: the fetch and search methods return None.
    """
    async def fetch_headline_news_async(self) -> List[News]:
        """Not implemented.

        Warnings
        --------
        Placeholder; returns None.
        """
        pass

    def search_by_keyword(self, keyword: str) -> List[News]:
        """Not implemented.

        Warnings
        --------
        Placeholder; returns None.
        """
        pass

    def get_provider_name(self) -> str:
        """Return ``"StatementDog"``."""
        return "StatementDog"
