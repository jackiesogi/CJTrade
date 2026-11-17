"""Demo script: fetch cnyes headlines and ask Gemini for hashtags and a summary.

Warnings
--------
Running it as a script scrapes cnyes.com and calls the Gemini LLM
(non-deterministic, uses API quota; needs ``GEMINI_API_KEY``).
"""
import asyncio
import os

from cjtrade.pkgs.analytics.informational.news_client import *
from cjtrade.pkgs.llm.gemini import GeminiClient
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    client = GeminiClient(api_key=os.getenv("GEMINI_API_KEY"))
    # postman = Webscraper()
    # postman = NewsClient(provider_type=NewsProviderType.MOCK)
    postman = NewsClient(provider_type=NewsProviderType.CNYES)
    news = asyncio.run(postman.fetch_headline_news_async(n=5))
    for n in news:
        prompt = f"title:'{n.title}', content:'{n.content}'.\
            Provide one line hashtags separated by space without newline of:\
            - Related company,\
            - Related company stock code,\
            - Overall sentiment.\
            - Industry sector.\
            - Related product or service.\
            And summarize the news content in 50 words using original language."
        response = client.generate_response(prompt)
        print(f"Title: {n.title}\nSentiment Analysis:\n{response}\n")
