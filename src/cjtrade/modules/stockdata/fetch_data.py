import inspect
import random
import logging
import cjtrade.modules.stockdata._data_source_provider as DSP

log = logging.getLogger("cjtrade.modules.stockdata.fetch_data")

class PriceFetcher:
    def __init__(self):
        pass
    
    def GetPriceData(self, symbol: str):
        # call db_fetch() or sj_fetch() or yfinane_fetch()

        log.debug(f"Get price data of '{symbol}' via yfinance...")
        snapshot = DSP.GetPriceData(symbol)

        return snapshot