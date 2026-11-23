# Market data

Prices come from a `MarketData`, not from the account. A connected `client`
(see [Connect to a broker](connect.md)) has one at `client.market`: the
broker's own, or whichever you passed as `AccountClient(..., market=...)`.

## Latest quote

```python
for snap in client.market.get_snapshots(["2330", "0050"]):
    print(snap.symbol, snap.close, snap.volume)
```

A snapshot is a quote: its `open`, `high` and `low` are the trading day's so
far, not one bar's.

## Historical bars

```python
kbars = client.market.get_kbars("2330", "2025-01-01", "2025-10-01", "1d")

for k in kbars[-3:]:
    print(k.timestamp, k.open, k.high, k.low, k.close, k.volume)
```

The window is half-open: bars from `start` up to, not including, `end`.
Intervals are `1m`, `5m`, `15m`, `30m`, `1h` and `1d`, as far as the source
serves them (`client.market.capabilities.intervals`). Intraday bars are
stamped at the minute they close, daily bars at 09:00, and volume is in lots.

!!! warning
    Asking for an interval the source does not serve raises
    `UnsupportedRequest`; a window with no trading returns an empty list.

## Prices without a broker account

FinMind and Yahoo Finance need no brokerage account. Chain them with
`Fallback` and put the local price cache in front with `Cached`:

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))
bars = market.get_kbars("2330", "2025-01-01", "2025-10-01", "1d")
```

`FinMindMarketData` reads `FINMIND_TOKEN` from your settings and works
without one at a lower request limit. A free account serves daily bars;
minute bars and ticks need a FinMind sponsor plan, and until then
`Fallback` moves on to the next source.

To use a source of your own, subclass `MarketData`; see the
[Market data reference](../reference/market-data.md).

## Indicators

`ta` wraps TA-Lib and works on arrays:

```python
import numpy as np
from cjtrade.pkgs.analytics.technical import ta

closes = np.array([k.close for k in kbars])
ema = ta.ema(closes, 12)
upper, middle, lower = ta.bb(closes, 20)
macd, signal, hist = ta.macd(closes)
print(ema[-1], upper[-1], macd[-1])
```

Each result has the same length as the input, with `NaN` until the window
is full.

Next: [Write a strategy](strategy.md).
