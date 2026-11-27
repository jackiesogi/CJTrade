# 撰寫策略

這一頁會寫一個策略檔，檢查有沒有寫錯，並說明每個部分在做什麼。下一頁會拿它跑一整年的價格。

## 策略是什麼

策略是一個 Python 檔，裡面只有一個必要的函式 `on_bar`。每出現一根新的 K 棒，CJTrade 就會呼叫它一次，而它只會回答三種答案之一：

- `buy(...)`：我想買，
- `sell(...)`：我想賣，
- `hold("原因")`：這次不動作，並說明原因。

這個檔案從來不直接和券商溝通。`buy()` 只是表達「想買」的意圖；要不要真的下委託、下多少、怎麼送出，都由回測器或交易引擎決定。所以同一個檔案不用改，就能在回測、ArenaX 和真實帳戶上執行。

## 你的第一個策略

這是一個「布林通道」策略。布林通道是畫在近期平均價格上方和下方的兩條線。概念是：價格跌到下軌時算「便宜」，就買；漲到上軌時算「貴」，就賣。

把它存成 `my_strategy.py`：

```python linenums="1"
from cjtrade.pkgs.strategy.authoring import *

WINDOW = param.int(20, "Bollinger window", min=5, max=500)

def on_bar(bar, account):
    upper, middle, lower = ta.bb(bar.closes, WINDOW)
    if upper is None:
        return hold(f"warming up: {bar.bars_seen} of {WINDOW} bars")

    watch(upper=upper, lower=lower)

    if bar.close <= lower and not account.holding:
        return buy(reason="lower band touch")
    if bar.close >= upper and account.holding:
        return sell(reason="upper band touch")
    return hold("inside the bands")
```

逐行說明：

- **第 1 行**匯入策略可以用的所有東西：`ta`、`buy`、`sell`、`hold`、`param` 等等。不需要再 import 其他模組。
- **第 3 行**宣告一個「參數」，也就是你之後可能想調整的數字。這裡是 20，代表布林通道用幾根 K 棒來計算。標籤和範圍是給工具用的，讓它能把參數顯示成表單欄位。
- **第 5 行**是 CJTrade 每根 K 棒都會呼叫的函式。`bar` 是最新的一根 K 棒，加上它之前的歷史；`account` 是這個策略自己的錢和股票。
- **第 6 行**用目前為止的收盤價（`bar.closes`）算出布林通道。在策略裡，`ta.bb` 只回傳**最新**的三個值，不是整個陣列。
- **第 7-8 行**：K 棒還不到 20 根時，通道還算不出來，`ta.bb` 會回傳 `None`。這時策略先等待暖機，並說明原因。
- **第 10 行**的 `watch(...)` 記錄一些數字，讓你在 bot 執行時看到。它不影響交易。
- **第 12-15 行**是交易規則。這個策略持有股票時，`account.holding` 為 true，所以它不會連續買兩次，也不會賣出自己沒有的股票。
- **第 16 行**：其他情況一律不動作。

## 執行前先檢查

`strategy-tool check` 會讀取檔案並回報錯誤，不會真的進行任何交易：

```sh
uv run strategy-tool check < my_strategy.py
```

預期輸出：

```json
{"ok": true, "diagnostics": [], "params": [{"kind": "int", "default": 20, "label": "Bollinger window", "min": 5, "max": 500}]}
```

`"ok": true` 加上空的 `diagnostics` 清單，代表沒有發現問題。`params` 列出這個檔案宣告的參數。

現在故意把它改壞：把 `on_bar` 改名成 `on_bar_typo`，再把第 6 行的 `WINDOW` 拼錯成 `WINDW`，然後再檢查一次：

```json
{"ok": false, "diagnostics": [
  {"message": "a strategy needs a function called on_bar(bar, account)", "line": 1, "offset": 1, "severity": "error"},
  {"message": "WINDW is not defined. It is not part of the strategy API and nothing in this file sets it.", "line": 6, "offset": 1, "severity": "error"}
], "params": []}
```

每一筆診斷都會告訴你是哪一行、哪裡有問題。現在就抓到錯誤，總比跑了很久才在第一根 K 棒出錯好。

!!! danger "策略檔就是一般的 Python"
    檢查或執行策略時，都會真的執行這個檔案。它不是沙盒：只執行你信任的策略檔。

## 或者從範本開始

`strategy-tool` 可以幫你產生一個完整的起始檔案：

```sh
uv run strategy-tool templates
```

會列出有哪些種類：

| 種類 | 策略 |
|---|---|
| `bb` | 布林通道均值回歸（就像上面那個） |
| `dca` | 定期定額：每個月買固定金額，從不賣出 |
| `adx` | 盤勢切換：趨勢盤做突破，盤整盤做區間 |
| `blank` | 一個空的 `on_bar`，讓你自己填 |

把其中一個存成檔案（這個工具輸出的是 JSON，第二個指令負責把裡面的 `source` 欄位取出來）：

```sh
uv run strategy-tool template --kind dca \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > dca.py
```

## 策略可以用哪些東西

`bar`：正在處理的 K 棒，以及它之前的歷史：

| 名稱 | 內容 |
|---|---|
| `bar.close`、`bar.open`、`bar.volume`、`bar.time` | 這根 K 棒的值 |
| `bar.closes` | 到目前為止的所有收盤價，最舊的在前 |
| `bar.ago(n)` | `n` 根 K 棒之前的收盤價 |
| `bar.bars_seen` | 這個策略已經看過幾根 K 棒 |
| `bar.day_high`、`bar.day_low` | **當天**到目前為止的最高價和最低價（不是這根 K 棒的） |

`account`：這個策略自己的錢和股票：

| 名稱 | 內容 |
|---|---|
| `account.cash` | 這個策略可用的現金 |
| `account.equity` | 現金加上持股市值 |
| `account.shares`、`account.avg_cost` | 持有股數和平均成本 |
| `account.holding` | 有持股時為 `True` |

決策：

| 呼叫 | 意思 |
|---|---|
| `buy()` | 買到風控額度允許的上限 |
| `buy(100)` | 剛好買 100 股 |
| `buy(amount=10_000)` | 買大約 NT$10,000 的量，以整股計 |
| `buy(price=250.0)` | 用限價 250 下單，而不是用這根 K 棒的收盤價 |
| `sell()` | 賣出這個策略持有的全部股票 |
| `hold("原因")` | 不動作；原因會顯示在 bot 的狀態裡 |

工具：

| 名稱 | 用途 |
|---|---|
| `ta.bb`、`ta.sma`、`ta.ema`、`ta.rsi`、`ta.macd`、`ta.wma`、`ta.highest`、`ta.lowest`、`ta.efficiency` | 技術指標；每個都回傳最新的值，K 棒數不夠時回傳 `None` |
| `param.int`、`param.float`、`param.bool`、`param.choice` | 宣告一個可調整的值 |
| `state.x = ...` | 把一個值從這根 K 棒保留到下一根 |
| `watch(name=value)` | 在 bot 的狀態裡顯示一個數字 |
| `plot(name=value)` | 在圖上畫一條線 |

可以不寫的函式：`init()` 在第一根 K 棒之前執行一次，`on_fill(fill, account)` 在每次成交後執行，`on_end(account)` 在最後一根 K 棒之後執行。

`uv run strategy-tool api` 會列出每個名稱和它完整的簽名。

!!! warning "時間長度是用 K 棒數算的，不是天數"
    `ta.bb(bar.closes, 20)` 是 20 *根 K 棒*：在日 K 上是 20 個交易日，在 1 分 K 上是 20 分鐘。同一個檔案換了 K 棒週期，就是另一個策略。

!!! warning "目前的限制"
    - `bar` 只保留收盤價的歷史。`ta.adx`、`ta.atr` 和 `ta.stoch` 需要每根 K 棒的最高價和最低價，所以在策略檔裡不能用。
    - `param.*` 目前永遠回傳宣告時的預設值。要改值，請直接修改檔案。

下一步：[回測](backtesting.md)。
