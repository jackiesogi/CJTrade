from typing import List
from ._base import NewsInterface, News
import asyncio
from newsapi import NewsApiClient
from datetime import datetime, timedelta

class NewsAPIProvider(NewsInterface):
    def __init__(self, **config):
        super().__init__(**config)

        # check required config parameters like API key here
        required_params = ['api_key']
        for param in required_params:
            if param not in config:
                raise ValueError(f"Missing required config parameter: {param}")

        self.api_key = config['api_key']
        self.default_query = "Taiwan"
        self.today_date = datetime.today().strftime('%Y-%m-%d')


    def _response_to_news_list(self, response: dict) -> List[News]:
        news_list = []
        for article in response['articles']:
            title = article.get('title', 'No title')
            content = article.get('description', '') or article.get('content', '')[:200] + "..."
            news_list.append(News(title=title, content=content))
        return news_list


    async def fetch_news_async(self) -> List[News]:
        newsapi = NewsApiClient(api_key=self.api_key)
        all_articles = newsapi.get_top_headlines(q=self.default_query,
                                                 sources='bbc-news,the-verge',
                                                 category='business',
                                                 language='en',
                                                 country='tw')
        # all_articles = newsapi.get_everything(q=self.default_query,
        #                               sources='bbc-news,the-verge',
        #                               domains='bbc.co.uk,techcrunch.com',
        #                               from_param=(datetime.today() - timedelta(days=5)).strftime('%Y-%m-%d'),
        #                               to=self.today_date,
        #                               language='en',
        #                               sort_by='relevancy',
        #                               page=2)
        return self._response_to_news_list(all_articles)

    def fetch_news(self) -> List[News]:
        newsapi = NewsApiClient(api_key=self.api_key)
        all_articles = newsapi.get_top_headlines(q=self.default_query,
                                                 sources='bbc-news',
                                                #  category='business',
                                                 language='en')
                                                #  language='en',
                                                #  country='us')
        # print(all_articles)
        return self._response_to_news_list(all_articles)

    def search_by_keyword(self, keyword: str) -> List[News]:
        newsapi = NewsApiClient(api_key=self.api_key)
        all_articles = newsapi.get_everything(q=keyword,
                                      sources='bbc-news,the-verge',
                                    #   domains='bbc.co.uk,techcrunch.com',
                                      from_param=(datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d'),
                                      to=self.today_date,
                                      language='en',
                                      sort_by='relevancy',
                                      page=1)
        return self._response_to_news_list(all_articles)


    def get_provider_name(self) -> str:
        return "NewsAPI"