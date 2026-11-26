# 行情資料

價格來自一個 `MarketData`，不是來自帳戶。連線好的 `client`（見[連線到券商](connect.md)）
在 `client.market` 上就有一個：預設是券商自己的，或是你用
`AccountClient(..., market=...)` 傳進去的那個。

## 最新報價

```python
for snap in client.market.get_snapshots(["2330", "0050"]):
    print(snap.symbol, snap.close, snap.volume)
```

Snapshot 是一筆報價，它的 `open`、`high`、`low` 是當天到目前為止的值，不是某一根
K 棒的。

## 歷史 K 棒

```python
kbars = client.market.get_kbars("2330", "2025-01-01", "2025-10-01", "1d")

for k in kbars[-3:]:
    print(k.timestamp, k.open, k.high, k.low, k.close, k.volume)
```

區間是左閉右開：從 `start` 開始，到 `end` 之前為止，不包含 `end`。interval 有
`1m`、`5m`、`15m`、`30m`、`1h` 和 `1d`，實際能用哪些看資料來源
（`client.market.capabilities.intervals`）。分 K 標在收盤的那一分鐘，日 K 標在 09:00，
成交量以張為單位。

只會回傳已收盤的 K 棒。盤中還在成交的那一分鐘不會出現，當天的日 K 要 13:30 之後才有。
對 ArenaX 來說「現在」是模擬時鐘，所以回放時看不到還沒走到的 K 棒。同一個時間點，
Sinopac 和 ArenaX 回傳的 K 棒一樣。

!!! warning
    要求資料來源不支援的 interval 會丟出 `UnsupportedRequest`；沒有交易的區間會回傳
    空 list。

## 不用券商帳號取得價格

FinMind 和 Yahoo Finance 都不需要券商帳號。用 `Fallback` 串起來，再用 `Cached` 在前面
加上本機價格快取：

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))
bars = market.get_kbars("2330", "2025-01-01", "2025-10-01", "1d")
```

`FinMindMarketData` 會從設定讀取 `FINMIND_TOKEN`，沒有 token 也能用，只是請求上限較低。
免費帳號可以抓日 K；分 K 和逐筆要 FinMind 的贊助方案，在那之前 `Fallback` 會改問下一個
來源。

要接自己的資料來源，繼承 `MarketData` 即可，見[行情資料參考](../reference/market-data.md)。
只有逐筆資料的來源可以用 `bars_from_ticks` 組出 1 分 K，更粗的 interval 都由 1 分 K
彙總。

## 離線：自己的價格檔

先把 K 棒下載到一個自己的檔案，再讓 ArenaX 只讀這個檔案、不連任何網路來源：

```sh
uv run preload-prices --price-db exp.db --symbols 2330,2317 --start 2026-10-26
CJTRADE_OFFLINE=1 uv run arenaxd --backend=demo --data=offline --price-db=exp.db
```

`preload-prices` 預設抓 1m、5m、1h、1d（`--interval`），先問 FinMind 再問 Yahoo
（`--data`），而且只抓檔案裡還沒有的區間，所以再跑一次就是補資料。`--data=offline`
讓 ArenaX 只提供檔案裡有的資料：沒預載的 interval 或日期會回傳空的。`CJTRADE_OFFLINE=1`
讓所有網路來源（FinMind、Yahoo、Sinopac）直接丟出 `MarketDataUnavailable`，不會連線，
你自己程式裡的 `Cached(...)` 也適用。

!!! warning
    Yahoo 的 1 分 K 只保留約 30 天，而 demo backend 會從 11 到 20 天前開始。跑 demo
    請至少預載一個月。

## 技術指標

`ta` 包裝 TA-Lib，吃的是陣列：

```python
import numpy as np
from cjtrade.pkgs.analytics.technical import ta

closes = np.array([k.close for k in kbars])
ema = ta.ema(closes, 12)
upper, middle, lower = ta.bb(closes, 20)
macd, signal, hist = ta.macd(closes)
print(ema[-1], upper[-1], macd[-1])
```

每個結果的長度都和輸入相同，窗口湊滿之前是 `NaN`。

下一步：[撰寫策略](strategy.md)。
