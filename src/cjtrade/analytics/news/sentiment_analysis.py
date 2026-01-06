from cjtrade.analytics.news.news import News, Webscraper
from cjtrade.llm.gemini import GeminiClient
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

if __name__ == "__main__":
    client = GeminiClient(api_key=os.getenv("GEMINI_API_KEY"))
    postman = Webscraper()
    news = asyncio.run(postman.fetch_news())
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