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

Only closed bars are returned. During the session the minute still trading
is left out, and today's daily bar appears after 13:30. Against ArenaX,
"now" is the simulated clock, so a replay never shows a bar it has not
reached. Sinopac and ArenaX return the same bars for the same moment.

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
[Market data reference](../reference/market-data.md). A source that only has
ticks can build 1m bars with `bars_from_ticks`, and every coarser interval
is aggregated from 1m.

## Offline: a price file of your own

Download the bars once into a file of your own, then run ArenaX on that file
with no network source:

```sh
uv run preload-prices --price-db exp.db --symbols 2330,2317 --start 2026-10-26
CJTRADE_OFFLINE=1 uv run arenaxd --backend=demo --data=offline --price-db=exp.db
```

`preload-prices` fetches 1m, 5m, 1h and 1d bars by default (`--interval`)
from FinMind, then Yahoo (`--data`), and only fetches windows the file lacks,
so running it again tops the file up. `--data=offline` makes ArenaX serve
only what the file holds: an interval or a day that was not preloaded comes
back empty. `CJTRADE_OFFLINE=1` makes every network source (FinMind, Yahoo,
Sinopac) raise `MarketDataUnavailable` instead of connecting, which also
works for `Cached(...)` in your own code.

!!! warning
    Yahoo keeps only about 30 days of 1m bars, and the demo backend starts
    11 to 20 days back. Preload at least a month for a demo run.

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
