# 行情資料

價格從哪裡來，跟委託送到哪裡分開處理。每個資料來源都遵守同一套規則（區間為左閉右開、
K 棒標在收盤那一分鐘、不還原權值、成交量以張為單位），所以可以任意串接和快取。

!!! warning
    除了 `PriceCache` 以外，每個來源都會連網路。FinMind 和 Yahoo 對免費帳號能抓的
    歷史長度和請求次數都有限制。

::: cjtrade.pkgs.marketdata.base
    options:
      members: [MarketData, Capabilities, MarketDataError, UnsupportedRequest, MarketDataUnavailable]

::: cjtrade.pkgs.marketdata.compose

::: cjtrade.pkgs.marketdata.cache

::: cjtrade.pkgs.marketdata.finmind

::: cjtrade.pkgs.marketdata.yfinance

::: cjtrade.pkgs.marketdata.sinopac

::: cjtrade.pkgs.marketdata.arenax

::: cjtrade.pkgs.marketdata.factory

::: cjtrade.pkgs.marketdata.aggregate
