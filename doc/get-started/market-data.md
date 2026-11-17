# Market data

The examples assume a connected `client` (see
[Connect to a broker](connect.md)).

## Latest quote

```python
from cjtrade.pkgs.models.product import Product

for snap in client.get_snapshots([Product("2330"), Product("0050")]):
    print(snap.symbol, snap.close, snap.volume)
```

A snapshot is a quote: its `open`, `high` and `low` are the trading day's so
far, not one bar's.

## Historical bars

```python
kbars = client.get_kbars(Product("2330"), start="2025-01-01",
                         end="2025-10-01", interval="1d")

for k in kbars[-3:]:
    print(k.timestamp, k.open, k.high, k.low, k.close, k.volume)
```

Intervals are `1m`, `5m`, `1h` and `1d`; dates are `YYYY-MM-DD`.

!!! warning
    `get_kbars` returns an empty list, not an error, when there is no data
    for the range. On ArenaX an unsupported interval quietly falls back to
    `1m`.

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
