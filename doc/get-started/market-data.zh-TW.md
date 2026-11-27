# 行情資料

這一頁會用三種方式取得價格：從已連線的券商、從不需要券商的免費來源，以及從你電腦上的檔案。最後再算一個技術指標。

## 價格和下單是分開的

在 CJTrade 裡，「價格從哪裡來」和「委託送到哪裡」是兩件分開的事。連線後的 client 會把價格放在 `client.market`。用 ArenaX 時，價格是 ArenaX 自己重播的資料；用永豐金證券 Sinopac 時，就是 Sinopac 的行情。你也可以完全不接券商，單獨使用某個行情來源。

每個行情來源都回答同樣兩個問題：

- `get_snapshots(symbols)`：最新的即時報價是多少？
- `get_kbars(symbol, start, end, interval)`：這段時間區間裡的 K 棒是哪些？

## 從已連線的券商取得

先讓 ArenaX 跑起來（見[連線到券商](connect.md)）：

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

日期請用 ArenaX 模擬時鐘上的日期（也就是你在[連線到券商](connect.md)印出的 `market time`），不要用今天的日期。

預期輸出（你的日期和價格會不一樣）：

```text
2330 2370.0 251
Kbar(symbol=2330, timestamp=2026-11-10 09:00:00, open=2265.0, high=2285.0, low=2230.0, close=2285.0, volume=34243)
Kbar(symbol=2330, timestamp=2026-11-11 09:00:00, open=2330.0, high=2395.0, low=2305.0, close=2395.0, volume=30511)
Kbar(symbol=2330, timestamp=2026-11-12 09:00:00, open=2385.0, high=2395.0, low=2330.0, close=2340.0, volume=29205)
9 one-minute bars; the first: Kbar(symbol=2330, timestamp=2026-11-13 09:01:00, open=2375.0, ...)
```

怎麼看這些結果：

- **時間區間包含 `start`，但不包含 `end`。** 查 11 月 10 日到 13 日，拿到的是 10、11、12 日。
- **K 棒的時間戳記是它結束的時間。** 09:01 那根 K 棒涵蓋 09:00 到 09:01。日 K 的時間一律標成 09:00。
- **只會回傳已經走完的 K 棒。** 當時 ArenaX 的時鐘在 13 日 09:10，所以那天的日 K 還不存在；1 分 K 也只拿到 9 根，不是 10 根。
- **成交量的單位是張**（1,000 股）。
- **即時報價裡的開盤價、最高價、最低價是當天到目前為止的值**，不是某一根 K 棒的值。

## 不用券商：免費來源 {#without-a-broker-free-sources}

FinMind 和 Yahoo Finance 都不需要證券帳戶。用 `Fallback` 把它們排在一起（第一個查不到，就問下一個），外面再包一層 `Cached`，這樣每根 K 棒只會下載一次：

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

跑第二次會馬上出結果，因為 `Cached` 直接從你電腦上的價格快取讀取 K 棒。

各免費來源能提供的資料：

| 來源 | 日 K | 分 K | 備註 |
|---|---|---|---|
| FinMind | 有，可回溯好幾年 | 要付費方案才有 | 設定 `FINMIND_TOKEN` 可以提高請求上限；不設也能用 |
| Yahoo Finance | 有 | 只有最近約 30 天 | 查詢太頻繁會被限速 |

用上面的 `Fallback` 時，FinMind 給不了的分 K 請求，會改由 Yahoo 回答。

!!! warning "查詢沒有任何來源提供的資料"
    如果沒有任何來源支援某個 K 棒週期，會丟出 `UnsupportedRequest`。如果時間區間裡沒有交易（週末、假日），會回傳空的 list，不會報錯。

## 離線：自己的價格檔

想在沒有網路的情況下使用，或想讓每次執行結果都一樣，可以先用 `preload-prices` 把 K 棒一次下載到檔案裡：

```sh
uv run preload-prices --price-db prices.db --symbols 2357 --start 2026-11-02 --end 2026-11-21 --interval 1m,1d
```

| 選項 | 意思 |
|---|---|
| `--price-db prices.db` | 要寫入的檔案；不存在時會自動建立 |
| `--symbols 2357` | 要下載哪些股票，用逗號分隔 |
| `--start` / `--end` | 時間區間；不包含 `--end`，預設是明天 |
| `--interval 1m,1d` | 要哪些 K 棒週期；預設是 `1m,5m,1h,1d` |
| `--data` | 從哪裡下載；預設是 `finmind,yfinance` |

預期輸出：

```text
2357 1m: 3639 bars over 15 days (2026-11-02 09:01 .. 2026-11-20 13:25)
2357 1d: 15 bars over 15 days (2026-11-02 09:00 .. 2026-11-20 09:00)
3654 bars in prices.db
```

再執行一次時，只會下載檔案裡還沒有的部分。之後就能讓 ArenaX 完全不連網，直接讀這個檔案。[執行交易引擎](trading-engine.md)就是這樣做的。

## 技術指標

`ta` 用 TA-Lib 計算技術指標。輸入是 NumPy 陣列，回傳一個一樣長的陣列：

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

前四個 SMA 值是 `nan`（「不是數字」）：5 根 K 棒的平均，要先有 5 根 K 棒才算得出來。其他技術指標還有 `ta.ema`、`ta.rsi`、`ta.macd`，以及需要最高價、最低價、收盤價三者的 `ta.adx(highs, lows, closes)` 和 `ta.atr(highs, lows, closes)`。詳見[技術指標](../reference/technical.md)。

??? info "進階：自訂來源、tick、K 棒合成"
    - 繼承 `MarketData` 就能新增一個行情來源；見[行情資料參考](../reference/market-data.md)。
    - 只有 tick 資料的來源，可以用 `bars_from_ticks` 組出 1m K 棒。所有更長的 K 棒週期都是由 1m 合成的。
    - 設定 `CJTRADE_OFFLINE=1` 後，所有需要網路的來源都會丟出 `MarketDataUnavailable`，而不會去連線。這樣本來應該離線的執行，就不會偷偷下載資料。
    - `client.market.capabilities.intervals` 會列出某個來源支援的 K 棒週期。

下一步：[撰寫策略](strategy.md)。
