import inspect
import random
import cjtrade.modules.stockdata._data_source_provider as DSP
import cjtrade.modules.stockdata.fetch_data as FETCH_DATA


def PriceFetcher():
    return FETCH_DATA.PriceFetcher()