# 行情資料

取得價格有三種方式：從已連線的券商、從不需要券商的免費來源，以及從本機的價格檔。最後示範計算技術指標。

## 價格和下單是分開的

CJTrade 把行情來源和委託路由分開。連線後的 client 透過 `client.market` 提供價格：ArenaX 是它自己的重播資料，永豐金證券 Sinopac 則是 Sinopac 的行情。行情來源也可以不接券商、單獨使用。

每個行情來源都實作同樣兩個呼叫：

- `get_snapshots(symbols)`：各股票最新的即時報價。
- `get_kbars(symbol, start, end, interval)`：某個時間區間內的 K 棒。

## 從已連線的券商取得

先啟動 ArenaX（見[連線到券商](connect.md)）：

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

日期以 ArenaX 的模擬時鐘為準（即[連線到券商](connect.md)印出的 `market time`），不是今天的日期。

預期輸出（你的日期和價格會不一樣）：

```text
2330 2370.0 251
Kbar(symbol=2330, timestamp=2026-11-10 09:00:00, open=2265.0, high=2285.0, low=2230.0, close=2285.0, volume=34243)
Kbar(symbol=2330, timestamp=2026-11-11 09:00:00, open=2330.0, high=2395.0, low=2305.0, close=2395.0, volume=30511)
Kbar(symbol=2330, timestamp=2026-11-12 09:00:00, open=2385.0, high=2395.0, low=2330.0, close=2340.0, volume=29205)
9 one-minute bars; the first: Kbar(symbol=2330, timestamp=2026-11-13 09:01:00, open=2375.0, ...)
```

慣例：

- **時間區間是半開區間 `[start, end)`。** 查 11 月 10 日到 13 日，回傳 10、11、12 日。
- **K 棒以收盤時間標記。** 09:01 的 K 棒涵蓋 09:00 到 09:01。日 K 一律標為 09:00。
- **只回傳已收完的 K 棒。** 當時 ArenaX 的時鐘在 13 日 09:10，所以當天的日 K 還不存在，1 分 K 也只有 9 根，不是 10 根。
- **成交量單位是張**（1,000 股）。
- **即時報價的開盤價、最高價、最低價是當日至今的值**，不是單根 K 棒的值。

## 不用券商：免費來源 {#without-a-broker-free-sources}

FinMind 和 Yahoo Finance 都不需要證券帳戶。`Fallback` 依序查詢各來源，直到有一個回答；外層的 `Cached` 讓每根 K 棒只下載一次：

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))

kbars = market.get_kbars("2330", "2025-09-01", "2025-10-01", "1d")
print(len(kbars), "bars")
for k in kbars[-3:]:
    print(k)
```

預期輸出：

```text
21 bars
Kbar(symbol=2330, timestamp=2025-09-25 09:00:00, open=1320.0, high=1330.0, low=1320.0, close=1320.0, volume=27801)
Kbar(symbol=2330, timestamp=2025-09-26 09:00:00, open=1310.0, high=1315.0, low=1295.0, close=1300.0, volume=29379)
Kbar(symbol=2330, timestamp=2025-09-30 09:00:00, open=1310.0, high=1320.0, low=1305.0, close=1305.0, volume=44853)
```

第二次執行會立即回傳：`Cached` 從本機的價格快取讀取 K 棒。

各免費來源的涵蓋範圍：

| 來源 | 日 K | 分 K | 備註 |
|---|---|---|---|
| FinMind | 有，可回溯多年 | 僅付費方案 | `FINMIND_TOKEN` 可提高請求上限；非必要 |
| Yahoo Finance | 有 | 僅最近約 30 天 | 有限速 |

使用上面的 `Fallback` 時，FinMind 無法提供的分 K 請求會改由 Yahoo 回答。

!!! warning "查詢沒有任何來源提供的資料"
    沒有任何來源支援的 K 棒週期會丟出 `UnsupportedRequest`。區間內沒有交易（週末、假日）時回傳空的 list，不會報錯。

## 離線：自己的價格檔

需要離線或可重現的執行時，先用 `preload-prices` 把 K 棒一次下載到檔案：

```sh
uv run preload-prices --price-db prices.db --symbols 2357 --start 2026-11-02 --end 2026-11-21 --interval 1m,1d
```

| 選項 | 意思 |
|---|---|
| `--price-db prices.db` | 寫入的檔案；不存在時自動建立 |
| `--symbols 2357` | 股票代號，以逗號分隔 |
| `--start` / `--end` | 時間區間；不含 `--end`，預設為明天 |
| `--interval 1m,1d` | K 棒週期；預設 `1m,5m,1h,1d` |
| `--data` | 下載來源；預設 `finmind,yfinance` |

預期輸出：

```text
2357 1m: 3639 bars over 15 days (2026-11-02 09:01 .. 2026-11-20 13:25)
2357 1d: 15 bars over 15 days (2026-11-02 09:00 .. 2026-11-20 09:00)
3654 bars in prices.db
```

重複執行時只下載檔案中缺少的部分。之後 ArenaX 可以完全離線讀取這個檔案，[執行交易引擎](trading-engine.md)即採用這種方式。

## 技術指標

`ta` 封裝 TA-Lib。輸入 NumPy 陣列，回傳等長的陣列：

```python
import numpy as np
from cjtrade.pkgs.analytics.technical import ta

closes = np.array([k.close for k in kbars])      # kbars 來自上面的範例
sma = ta.sma(closes, 5)                          # 5 根 K 棒的簡單移動平均
upper, middle, lower = ta.bb(closes, 20)         # 20 根 K 棒的布林通道

print("last closes:", closes[-3:])
print("SMA(5):     ", sma[-3:])
print("first SMA:  ", sma[:5])
print("BB(20):     ", round(upper[-1], 2), round(middle[-1], 2), round(lower[-1], 2))
```

預期輸出：

```text
last closes: [1320. 1300. 1305.]
SMA(5):      [1312. 1319. 1321.]
first SMA:   [  nan   nan   nan   nan 1165.]
BB(20):      1367.94 1250.75 1133.56
```

輸出與輸入對齊，暖機期間的值為 `nan`（SMA(5) 的前四個值）。其他技術指標包括 `ta.ema`、`ta.rsi`、`ta.macd`，以及需要最高價、最低價、收盤價三個陣列的 `ta.adx(highs, lows, closes)` 和 `ta.atr(highs, lows, closes)`。詳見[技術指標](../reference/technical.md)。

??? info "進階：自訂來源、tick、K 棒合成"
    - 繼承 `MarketData` 可新增行情來源；見[行情資料參考](../reference/market-data.md)。
    - 只有 tick 資料的來源，可用 `bars_from_ticks` 組出 1m K 棒。所有更長的 K 棒週期都由 1m 合成。
    - 設定 `CJTRADE_OFFLINE=1` 後，所有需要網路的來源都會丟出 `MarketDataUnavailable`，不會連線，因此離線執行不會在背後下載資料。
    - `client.market.capabilities.intervals` 會列出某個來源支援的 K 棒週期。

下一步：[撰寫策略](strategy.md)。
