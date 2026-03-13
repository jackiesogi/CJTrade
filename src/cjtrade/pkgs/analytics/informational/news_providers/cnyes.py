# 鉅亨網 CNYES: No official API, so we do web scraping
import asyncio
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
    def get_newslist_info(self, page=1, limit=30):
        """
        :param page: 頁數
        :param limit: 一頁新聞數量
        :return newslist_info: 新聞資料
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
        """
        Async version of get_newslist_info
        :param page: 頁數
        :param limit: 一頁新聞數量
        :return newslist_info: 新聞資料
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
        # Remove HTML tags, replace entities, clean up whitespace
        clean_content = re.sub(r'<[^>]+>', '', html_content)
        clean_content = clean_content.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        clean_content = ' '.join(clean_content.split())
        return clean_content


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
            # Use summary as content, fallback to cleaned HTML content
            summary = item.get('summary', '')
            content = summary or self._clean_html_content(item.get('content', ''))[:500]

            if title and content:  # Only add if both title and content exist
                news_list.append(News(title=title, content=content))

        return news_list


    async def fetch_headline_news_async(self, n: int = 10) -> List[News]:
        delay = random.uniform(1, 3)
        await asyncio.sleep(delay)

        try:
            newslist_info = await self.spider.get_newslist_info_async(page=1, limit=n)
            return self._convert_to_news_list(newslist_info, n)
        except Exception as e:
            print(f"Error fetching news from CNYES: {e}")
            return []


    def fetch_headline_news(self, n: int = 10) -> List[News]:
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

                    content = summary or self._clean_html_content(item.get('content', ''))[:500]
                    filtered_news.append(News(title=title, content=content))

                    if len(filtered_news) >= n:
                        break

            return filtered_news
        except Exception as e:
            print(f"Error searching news from CNYES: {e}")
            return []


    def get_provider_name(self) -> str:
        return "cnyes"
