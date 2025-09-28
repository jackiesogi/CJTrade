import logging
import cjtrade.modules.llm as LLM

log = logging.getLogger("cjtrade.modules.news")

# 應該看要不要寫成有 class 暫存那些獲取下來的資訊，或是就直接放入 db 再讀出來

def RunWebCrawler():
    log.info(f"Starting the web crawler on online information ...")
    return ["this is the mock information about HP Inc.",
            "this is another mock info about TSMC"]


def GetMarketSentimentAnalysis(llm, information) -> float:
    symbol = llm.GetSymbolFromText(information)
    score = llm.GetSentimentScore(symbol, information)
    return score


# TODO: 把 news 和 llm 抽象畫並且看要不要把它們都包到一個 AppContext 裡面
# def GetHighInterested(llm):
def GetHighInterested():
    log.debug("Fetching high interested stock ...")
    result_stub_list = ['1111', '5555']
    # information = RunWebCrawler()
    # GetMarketSentimentAnalysis()
    # result_stub_list = []
    return result_stub_list


# def GetLowInterested(llm):
def GetLowInterested():
    log.debug("Fetching low interested stock ...")
    result_stub_list = ['7357', '00515', '6789', '3240', '2515']
    # result_stub_list = []
    return result_stub_list