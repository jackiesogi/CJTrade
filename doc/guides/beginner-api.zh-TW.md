# Beginner API

`cjtrade.pkgs.api.beginner` 是一組簡短的函式，方便在 REPL 或 notebook 裡操作券商：
一個全域的 client、一個目前的股票代號，出錯時印出錯誤並回傳預設值，不會丟出例外。

!!! warning "給 REPL 用，不是給 bot 用"
    這裡的 `buy()` 和 `sell()` 會直接透過全域 client 下單。要在 engine 風控底下執行
    的策略，請改用 [authoring 模組](strategy-authoring.md)撰寫。

## 連線

```python
from cjtrade.pkgs.api.beginner import *
from cjtrade.pkgs.brokers.account_client import BrokerType

client = create_client(BrokerType.ARENAX)   # 環境變數需要 API_KEY=testkey123
set_client(client)
set_current_symbol("2330")
```

`create_client` 會從環境變數（以及 `.env` 檔）讀取 `API_KEY`、`SECRET_KEY`、
`CA_CERT_PATH` 和 `CA_PASSWORD`，建立 `AccountClient` 並連線。ArenaX 必須在執行中，
見[快速開始](quickstart.md)。

!!! warning "一定要指定券商類型"
    預設值 `BrokerType.MOCK` 已經不存在，用了會失敗。如果在 `set_client()` 之前就
    呼叫 `buy()` 或查詢函式，模組會嘗試建立這個預設 client，也會同樣失敗。

!!! danger "永豐是真實帳戶"
    `create_client(BrokerType.SINOPAC)` 會連到你的真實帳戶（這裡的預設是
    `simulation=False`）。要用永豐的模擬環境請傳 `simulation=True`。

## 查詢

| 函式 | 別名 | 回傳 | 出錯時 |
|---|---|---|---|
| `get_current_price(symbol=None)` | `snapshot_price` | snapshot 的最新收盤價 | `None` |
| `get_balance()` | `cash` | 現金，新台幣 | `0.0` |
| `get_total_equity()` | `equity` | 現金加持倉市值 | `0.0` |
| `get_positions()` | `positions` | `Position` 的 list | `[]` |
| `get_kbars(symbol, start, end, interval="1d")` | `kbars` | `Kbar` 的 list | `None` |
| `get_kbar_series(symbol, start, end, interval="1d")` | `series` | `KbarSeries` | `None` |

```python
print(get_current_price(), cash(), equity())

for p in positions():
    print(p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl)

bars = get_kbars("2330", "2025-09-01", "2025-09-05")
print(bars[0].timestamp, bars[0].close)
```

`start` 和 `end` 的格式是 `YYYY-MM-DD`。interval 有 `1m`、`5m`、`1h` 和 `1d`。

!!! warning "出錯看起來像空的結果"
    這些函式出錯時會印出錯誤，並回傳表格裡的預設值。現金 `0.0` 或空的持倉，也可能
    代表連不上券商。只有沒指定股票代號時會丟出 `ValueError`。

## 技術指標

`ta` 包裝 TA-Lib，吃的是陣列，所以要用 `KbarSeries`，它把 `closes`、`opens`、
`highs`、`lows` 和 `volumes` 存成 NumPy 陣列：

```python
s = get_kbar_series("2330", "2025-08-01", "2025-09-30")
ema = ta.ema(s.closes, 12)                 # 陣列；ema[-1] 是最新值
rsi = ta.rsi(s.closes, 14)
upper, middle, lower = ta.bb(s.closes, 20)
macd, signal, hist = ta.macd(s.closes)
print(s.close, ema[-1], rsi[-1])
```

另外還有 `ta.sma`、`ta.wma`，以及吃 `(high, low, close, ...)` 的 `ta.stoch`、
`ta.atr`、`ta.adx`。在窗口湊滿之前，陣列前面的值是 `NaN`。

!!! note
    這裡的 `ta` 回傳整個陣列。authoring 模組裡的 `ta` 只回傳最新一個值，資料不夠時
    回傳 `None`。

## 下單

```python
r = buy(qty=1, price=1000.0)            # 限價單，1 股（零股）
print(r.status)
r = sell_order(qty=1, price=1500.0, symbol="2330")
```

兩者都回傳 `OrderResult`（`status`、`message`、`linked_order`），呼叫本身失敗時回傳
`None`。預設 `intraday_odd=True`，所以 `qty` 的單位是股。

!!! danger "一定要給價格"
    `price=None` 會被當成限價 `0` 送出，不是市價單。

!!! warning
    賣出帳戶沒有的股票時，ArenaX 會回傳 `REJECTED` 的結果，不會丟出例外，所以要
    檢查 `r.status`。

## 資料模型

| Class | 常用欄位 |
|---|---|
| `Order` | `id`、`product`、`action`（`OrderAction.BUY` / `SELL`）、`price`、`quantity`、`price_type`、`order_type`、`order_lot` |
| `OrderType` | 委託效期：`ROD`、`IOC`、`FOK`、`GTC` |
| `Product` | `Product("2330")` |
| `Position` | `symbol`、`quantity`、`avg_cost`、`current_price`、`market_value`、`unrealized_pnl` |
| `Kbar` | `timestamp`、`open`、`high`、`low`、`close`、`volume`、`symbol` |

完整簽名請見 [API 參考](../reference/beginner.md)。
