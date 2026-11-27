# Market data

In this page you get prices three ways: from the broker you are connected
to, from free sources without any broker, and from a file on your disk. At
the end you compute an indicator.

## Prices come from a separate place

In CJTrade, *where prices come from* is separate from *where orders go*. A
connected client has its prices at `client.market`. On ArenaX that is
ArenaX's own replay; on Sinopac it is Sinopac's feed. You can also use a
price source on its own, with no broker at all.

Every source answers the same two questions:

- `get_snapshots(symbols)`: what is the latest quote?
- `get_kbars(symbol, start, end, interval)`: what were the bars in this
  window?

## From the broker you are connected to

With ArenaX running ([Connect to a broker](connect.md)):

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

for snap in client.market.get_snapshots(["2330"]):
    print(snap.symbol, snap.close, snap.volume)

daily = client.market.get_kbars("2330", "2026-11-10", "2026-11-13", "1d")
for k in daily:
    print(k)

minutes = client.market.get_kbars("2330", "2026-11-13 09:00", "2026-11-13 09:10", "1m")
print(len(minutes), "one-minute bars; the first:", minutes[0])

client.disconnect()
```

Use dates from ArenaX's simulated clock (the `market time` you printed in
[Connect to a broker](connect.md)), not today's date.

Expected output (your dates and prices will differ):

```text
2330 2370.0 251
Kbar(symbol=2330, timestamp=2026-11-10 09:00:00, open=2265.0, high=2285.0, low=2230.0, close=2285.0, volume=34243)
Kbar(symbol=2330, timestamp=2026-11-11 09:00:00, open=2330.0, high=2395.0, low=2305.0, close=2395.0, volume=30511)
Kbar(symbol=2330, timestamp=2026-11-12 09:00:00, open=2385.0, high=2395.0, low=2330.0, close=2340.0, volume=29205)
9 one-minute bars; the first: Kbar(symbol=2330, timestamp=2026-11-13 09:01:00, open=2375.0, ...)
```

How to read it:

- **The window includes `start` and stops before `end`.** Asking for 10 to
  13 November returns the 10th, 11th and 12th.
- **A bar's timestamp is when it ends.** The 09:01 bar covers 09:00 to 09:01.
  Daily bars are stamped 09:00.
- **Only finished bars are returned.** ArenaX's clock was at 09:10 on the
  13th, so that day's daily bar does not exist yet, and you got 9 one-minute
  bars, not 10.
- **Volume is in lots** (1,000 shares).
- **A snapshot's open, high and low are the whole day's so far**, not one
  bar's.

## Without a broker: free sources {#without-a-broker-free-sources}

FinMind and Yahoo Finance need no brokerage account. Put them one after the
other with `Fallback` (if the first has no answer, ask the next), and wrap
that in `Cached` so each bar is downloaded only once:

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))

kbars = market.get_kbars("2330", "2025-09-01", "2025-10-01", "1d")
print(len(kbars), "bars")
for k in kbars[-3:]:
    print(k)
```

Expected output:

```text
21 bars
Kbar(symbol=2330, timestamp=2025-09-25 09:00:00, open=1320.0, high=1330.0, low=1320.0, close=1320.0, volume=27801)
Kbar(symbol=2330, timestamp=2025-09-26 09:00:00, open=1310.0, high=1315.0, low=1295.0, close=1300.0, volume=29379)
Kbar(symbol=2330, timestamp=2025-09-30 09:00:00, open=1310.0, high=1320.0, low=1305.0, close=1305.0, volume=44853)
```

Run it twice: the second time is instant, because `Cached` reads the bars
from the price cache on your disk.

What each free source gives you:

| Source | Daily bars | Minute bars | Notes |
|---|---|---|---|
| FinMind | yes, years back | only with a paid plan | set `FINMIND_TOKEN` for a higher request limit; works without |
| Yahoo Finance | yes | the last ~30 days only | rate-limited if you ask too often |

With the `Fallback` above, a minute-bar request that FinMind cannot serve is
answered by Yahoo.

!!! warning "Asking for something no source has"
    An interval no source serves raises `UnsupportedRequest`. A window with
    no trading (a weekend, a holiday) returns an empty list, not an error.

## Offline: your own price file

To work without the network, or to make a run repeatable, download the bars
once into a file with `preload-prices`:

```sh
uv run preload-prices --price-db prices.db --symbols 2357 --start 2026-11-02 --end 2026-11-21 --interval 1m,1d
```

| Option | Meaning |
|---|---|
| `--price-db prices.db` | the file to fill; created if missing |
| `--symbols 2357` | which stocks, comma-separated |
| `--start` / `--end` | the window; `--end` is not included and defaults to tomorrow |
| `--interval 1m,1d` | which bar sizes; default `1m,5m,1h,1d` |
| `--data` | where to download from; default `finmind,yfinance` |

Expected output:

```text
2357 1m: 3639 bars over 15 days (2026-11-02 09:01 .. 2026-11-20 13:25)
2357 1d: 15 bars over 15 days (2026-11-02 09:00 .. 2026-11-20 09:00)
3654 bars in prices.db
```

Running it again only downloads what the file is missing. You can then run
ArenaX on that file with no network at all, which
[Run the trading engine](trading-engine.md) does.

## Indicators

`ta` calculates indicators with TA-Lib. It takes a NumPy array and returns
an array of the same length:

```python
import numpy as np
from cjtrade.pkgs.analytics.technical import ta

closes = np.array([k.close for k in kbars])      # kbars from the example above
sma = ta.sma(closes, 5)                          # 5-bar simple moving average
upper, middle, lower = ta.bb(closes, 20)         # Bollinger bands over 20 bars

print("last closes:", closes[-3:])
print("SMA(5):     ", sma[-3:])
print("first SMA:  ", sma[:5])
print("BB(20):     ", round(upper[-1], 2), round(middle[-1], 2), round(lower[-1], 2))
```

Expected output:

```text
last closes: [1320. 1300. 1305.]
SMA(5):      [1312. 1319. 1321.]
first SMA:   [  nan   nan   nan   nan 1165.]
BB(20):      1367.94 1250.75 1133.56
```

The first four SMA values are `nan` ("not a number"): a 5-bar average needs
5 bars before it has a value. Other indicators include `ta.ema`, `ta.rsi`,
`ta.macd`, and `ta.adx(highs, lows, closes)` and `ta.atr(highs, lows, closes)`, which need all three; see
[Technical indicators](../reference/technical.md).

??? info "For advanced users: your own source, ticks, aggregation"
    - Subclass `MarketData` to add a source; see the
      [Market data reference](../reference/market-data.md).
    - A source that only has ticks can build 1m bars with
      `bars_from_ticks`. Every coarser interval is aggregated from 1m.
    - `CJTRADE_OFFLINE=1` makes every network source raise
      `MarketDataUnavailable` instead of connecting, so a run that is meant
      to be offline cannot quietly download.
    - `client.market.capabilities.intervals` lists the intervals a source
      serves.

Next: [Write a strategy](strategy.md).
