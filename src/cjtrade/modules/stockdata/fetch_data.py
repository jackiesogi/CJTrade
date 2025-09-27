import inspect
import random
import logging
import cjtrade.modules.stockdata._data_source_provider as DSP
import cjtrade.modules.stockdata._database as DB

log = logging.getLogger("cjtrade.modules.stockdata.fetch_data")

def GetPriceData(symbol: str):
    # call db_fetch() or sj_fetch() or yfinane_fetch()

    log.debug(f"Get price data of '{symbol}' via yfinance...")
    snapshot = DSP.GetPriceData(symbol)

    return snapshot