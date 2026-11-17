# 鉅亨網 CNYES: No official API, so we do web scraping
import asyncio
import html as _html
import random
import re
import time
from typing import List

import aiohttp
import requests

from ._base import News
from ._base import NewsInterface

##############################################################################

# Source: https://blog.jiatool.com/posts/cnyes_news_spider by Jia
class CnyesNewsSpider():
    """Scraper for the cnyes.com (鉅亨網) headline news list.

    Warnings
    --------
    Scrapes the unofficial cnyes.com news API; results change over time and
    may break if the site changes.
    """
    def get_newslist_info(self, page=1, limit=30):
        """Fetch one page of cnyes headline news.

        Parameters
        ----------
        page : int
            頁數 (page number).
        limit : int
            一頁新聞數量 (news items per page).

        Returns
        -------
        dict or None
            新聞資料: ``{'data': [item, ...]}``, or None if the request or parsing fails.

        Warnings
        --------
        Scrapes the unofficial cnyes.com news API; results change over time and
        may break if the site changes.
        """
        headers = {
            'Origin': 'https://news.cnyes.com/',
            'Referer': 'https://news.cnyes.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
        r = requests.get(f"https://api.cnyes.com/media/api/v1/newslist/category/headline?page={page}&limit={limit}", headers=headers)
        if r.status_code != requests.codes.ok:
            print('請求失敗', r.status_code)
            return None
        # Return the full response with items in 'data' key for consistency
        try:
            data = r.json()
            # API structure: {'items': {'data': [...]}} or potentially {'data': [...]}
            if isinstance(data, dict):
                # Primary: try items.data (pagination object)
                items = data.get('items', {})
                if isinstance(items, dict):
                    items = items.get('data', [])
                elif not isinstance(items, list):
                    # Fallback: try direct 'data' key
                    items = data.get('data', [])

                # Final check: ensure items is a list
                if not isinstance(items, list):
                    items = []
            elif isinstance(data, list):
                items = data
            else:
                items = []
            return {'data': items}
        except Exception as e:
            print(f'Failed to parse CNYES response: {e}')
            return None

    async def get_newslist_info_async(self, page=1, limit=30):
        """Async version of get_newslist_info.

        Parameters
        ----------
        page : int
            頁數 (page number).
        limit : int
            一頁新聞數量 (news items per page).

        Returns
        -------
        dict or None
            新聞資料: ``{'data': [item, ...]}``, or None if the request fails.

        Warnings
        --------
        Scrapes the unofficial cnyes.com news API; results change over time and
        may break if the site changes.
        """
        headers = {
            'Origin': 'https://news.cnyes.com/',
            'Referer': 'https://news.cnyes.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.cnyes.com/media/api/v1/newslist/category/headline?page={page}&limit={limit}", headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        # API structure: {'items': {'data': [...]}} or potentially {'data': [...]}
                        if isinstance(data, dict):
                            # Primary: try items.data (pagination object)
                            items = data.get('items', {})
                            if isinstance(items, dict):
                                items = items.get('data', [])
                            elif not isinstance(items, list):
                                # Fallback: try direct 'data' key
                                items = data.get('data', [])

                            # Final check: ensure items is a list
                            if not isinstance(items, list):
                                items = []
                        elif isinstance(data, list):
                            items = data
                        else:
                            items = []
                        return {'data': items}
                    else:
                        print('請求失敗', response.status)
                        return None
        except Exception as e:
            print(f'Async request failed: {e}')
            return None

##############################################################################

class CnyesProvider(NewsInterface):
    """News provider for cnyes.com (鉅亨網) headlines.

    Warnings
    --------
    Scrapes the unofficial cnyes.com news API; results change over time and
    may break if the site changes.
    """
    def __init__(self, **config):
        super().__init__(**config)
        self.config = config
        self.spider = CnyesNewsSpider()
        self.headers = {
            'Origin': 'https://news.cnyes.com/',
            'Referer': 'https://news.cnyes.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }


    def _clean_html_content(self, html_content: str) -> str:
        if not html_content:
            return ""
        # Decode entities first (e.g. &lt;p&gt; → <p>, &quot; → ", &#39; → ')
        # so that entity-encoded tags are normalised before the regex runs.
        text = _html.unescape(html_content)
        # Strip all HTML/XML tags
        text = re.sub(r'<[^>]*>', '', text)
        # Normalise whitespace
        return ' '.join(text.split())


    def _convert_to_news_list(self, newslist_info, n: int = 10) -> List[News]:
        """Convert CNYES API response to News objects"""
        if not newslist_info:
            return []

        # Handle both dict format and direct list format
        if isinstance(newslist_info, dict):
            data = newslist_info.get('data', [])
        elif isinstance(newslist_info, list):
            data = newslist_info
        else:
            return []

        # Ensure data is a list
        if not isinstance(data, list):
            return []

        news_list = []
        # Safely iterate with limit
        for item in data[:n]:
            if not isinstance(item, dict):
                continue

            title = item.get('title', 'No Title')
            # Prefer full article content; fall back to summary if content is absent.
            content = (
                self._clean_html_content(item.get('content', ''))
                or self._clean_html_content(item.get('summary', ''))
            )

            if title and content:  # Only add if both title and content exist
                news_list.append(News(title=title, content=content))

        return news_list


    async def fetch_headline_news_async(self, n: int = 10) -> List[News]:
        """Fetch up to `n` cnyes headlines asynchronously.

        Returns
        -------
        list of News
            Empty on error.

        Warnings
        --------
        Sleeps a random 1-3 s, then scrapes cnyes.com; results change over time.
        """
        delay = random.uniform(1, 3)
        await asyncio.sleep(delay)

        try:
            newslist_info = await self.spider.get_newslist_info_async(page=1, limit=n)
            return self._convert_to_news_list(newslist_info, n)
        except Exception as e:
            print(f"Error fetching news from CNYES: {e}")
            return []


    def fetch_headline_news(self, n: int = 10) -> List[News]:
        """Fetch up to `n` cnyes headlines (blocking).

        Returns
        -------
        list of News
            Empty on error.

        Warnings
        --------
        Sleeps a random 1-3 s, then scrapes cnyes.com; results change over time.
        """
        delay = random.uniform(1, 3)
        time.sleep(delay)

        try:
            newslist_info = self.spider.get_newslist_info(page=1, limit=n)
            return self._convert_to_news_list(newslist_info, n)
        except Exception as e:
            print(f"Error fetching news from CNYES: {e}")
            return []


    # TODO: Currently we still search from headlines only, to be improved later
    def search_by_keyword(self, keyword: str, n: int = 10) -> List[News]:
        """Return up to `n` of the latest 50 headlines matching `keyword`.

        Matches case-insensitively against title, summary and the item's keywords.
        Only headlines are searched, not the full archive.

        Returns
        -------
        list of News
            Empty on error.

        Warnings
        --------
        Scrapes the unofficial cnyes.com news API; results change over time and
        may break if the site changes.
        """
        try:
            newslist_info = self.spider.get_newslist_info(page=1, limit=50)
            if not newslist_info or not isinstance(newslist_info, dict) or 'data' not in newslist_info:
                return []

            filtered_news = []
            for item in newslist_info['data']:
                if not isinstance(item, dict):
                    continue

                title = item.get('title', '')
                summary = item.get('summary', '')
                keywords = item.get('keyword', [])

                # Safely convert keywords to string
                if isinstance(keywords, list):
                    keyword_str = ' '.join(str(k) for k in keywords)
                else:
                    keyword_str = str(keywords) if keywords else ''

                # Safely convert to lowercase for comparison
                title_lower = str(title).lower() if title else ''
                summary_lower = str(summary).lower() if summary else ''
                keyword_str_lower = keyword_str.lower() if keyword_str else ''

                if (keyword.lower() in title_lower or
                    keyword.lower() in summary_lower or
                    keyword.lower() in keyword_str_lower):

                    content = (
                        self._clean_html_content(item.get('content', ''))
                        or self._clean_html_content(summary)
                    )
                    filtered_news.append(News(title=title, content=content))

                    if len(filtered_news) >= n:
                        break

            return filtered_news
        except Exception as e:
            print(f"Error searching news from CNYES: {e}")
            return []


    def get_provider_name(self) -> str:
        """Return ``"cnyes"``."""
        return "cnyes"
