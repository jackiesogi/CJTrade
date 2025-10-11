import logging
import requests
from bs4 import BeautifulSoup
import time
import random
import cjtrade.modules.llm as LLM
# from .. import llm as LLM

log = logging.getLogger("cjtrade.modules.news")

def RunWebCrawler():
    """簡單的新聞爬蟲，失敗返回 None"""
    log.info("Starting the web crawler on online information...")

    urls = [
        "https://news.cnyes.com/news/cat/tw_stock",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    news_list = []
    
    for url in urls:
        try:
            log.info(f"Crawling {url}")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 簡單提取標題
                titles = soup.find_all(['h1', 'h2', 'h3', 'h4'], limit=5)
                for title in titles:
                    text = title.get_text().strip()
                    if len(text) > 10:  # 過濾太短的標題
                        news_list.append(text)
                
                # log.info(f"Found {len(titles)} news from {url}")
                
            # 延遲避免被擋
            time.sleep(random.uniform(1, 3))
            
        except Exception as e:
            log.error(f"Error crawling {url}: {e}")
            continue
    
    if news_list:
        # log.info(f"Successfully crawled {len(news_list)} news items")
        log.debug(f"the crawled news items: {news_list}")
        return news_list
    else:
        log.warning("Failed to crawl any news, returning None")
        return None


def GetMarketSentimentAnalysis(llm, information) -> float:
    # (symbol, score, confidence)
    results = {}
    for info in information:
        symbol = llm.GetSymbolFromText(info)
        # if there is already have news about this symbol, we need to re-evaluate
        score, confidence = llm.GetSentimentScore(symbol, info)
        if symbol in results:
            prev_score, prev_confidence = results[symbol]
            # If the new confidence is higher, update the result
            if confidence > prev_confidence:
                results[symbol] = (score, confidence)
        else:
            results[symbol] = (score, confidence)
    return results


# def GetHighInterested(llm):
def GetHighInterested():
    log.debug("Fetching high interested stock ...")
    result_stub_list = ['1111', '5555']
    # info = RunWebCrawler()
    # result = GetMarketSentimentAnalysis(llm, info)
    # if score > 0.5:
    # result_stub_list = []
    return result_stub_list


# def GetLowInterested(llm):
def GetLowInterested():
    log.debug("Fetching low interested stock ...")
    result_stub_list = ['7357', '00515', '6789', '3240', '2515']
    # result_stub_list = []
    return result_stub_list


# if __name__ == "__main__":
#     news = RunWebCrawler()
#     if news:
#         # print(f"爬到 {len(news)} 則新聞")
#         print(news)
#     else:
#         print("爬蟲失敗")

#     high_stocks = GetHighInterested()
#     # print(f"High Interested Stocks: {high_stocks}")

#     low_stocks = GetLowInterested()
#     # print(f"Low Interested Stocks: {low_stocks}")

#     llm = LLM.LargeLanguageModel(backend=LLM.LLMBackend.OLLAMA)
    
#     prompt = f"How's the reputation of Taiwan company:{high_stocks[0]}, summarize in one sentence."
#     response = llm.SendPrompt(prompt)
#     print(f"LLM Response to '{prompt}': {response}")