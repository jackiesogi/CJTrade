# Market data

Where prices come from, separate from where orders go. Every source follows
the same conventions (half-open windows, bars stamped at their close, raw
prices, volume in lots), so sources can be chained and cached freely.

!!! warning
    Every source except `PriceCache` makes network calls. FinMind and Yahoo
    limit how much history and how many requests a free account gets.

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
