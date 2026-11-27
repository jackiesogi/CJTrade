# 撰寫策略

本頁說明如何撰寫策略檔、做靜態檢查，以及策略 API。下一頁用一年的價格回測它。

## 策略是什麼

策略是一個 Python 檔，唯一必要的函式是 `on_bar`。每根新 K 棒 CJTrade 會呼叫它一次，回傳值為以下之一：

- `buy(...)`：買進意圖，
- `sell(...)`：賣出意圖，
- `hold("原因")`：這根 K 棒不動作，並附上原因。

策略檔不直接和券商溝通。`buy()` 只表達意圖；是否下委託、數量多少、如何送出，由回測器或交易引擎決定。因此同一個檔案不需修改，就能在回測、ArenaX 和真實帳戶上執行。

## 你的第一個策略

布林通道均值回歸策略：觸及下軌時買進，觸及上軌時賣出。存成 `my_strategy.py`：

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

| 行 | 說明 |
|---|---|
| 1 | 星號匯入提供完整的策略語彙（`ta`、`buy`、`sell`、`hold`、`param` 等），不需要其他 import。 |
| 3 | `param.int(default, label, min=, max=)` 宣告可調參數，這裡是 20 根 K 棒的通道長度。工具把參數顯示成表單欄位時，會使用標籤和範圍。 |
| 5 | `on_bar` 每根 K 棒呼叫一次。`bar` 是最新的 K 棒加上之前的歷史；`account` 是這個策略自己的現金和持股。 |
| 6 | 以 `bar.closes` 計算布林通道。在策略裡，`ta.bb` 只回傳**最新**的三個值，不是陣列。 |
| 7-8 | 不足 20 根 K 棒時 `ta.bb` 回傳 `None`，策略以 hold 等待暖機並附上原因。hold 的原因會顯示在 bot 的狀態裡。 |
| 10 | `watch(...)` 記錄 bot 執行時要顯示的數值。僅供顯示，不影響交易。 |
| 12-15 | 進出場規則。`account.holding` 以策略為單位（這個策略有持股時為 true），所以不會連續買兩次，也不會賣出自己沒有的股票。 |
| 16 | 其餘情況 hold。 |

## 執行前先檢查

`strategy-tool check` 回報錯誤，不執行任何交易：

```sh
uv run strategy-tool check < my_strategy.py
```

預期輸出：

```json
{"ok": true, "diagnostics": [], "params": [{"kind": "int", "default": 20, "label": "Bollinger window", "min": 5, "max": 500}]}
```

`"ok": true` 且 `diagnostics` 為空清單代表沒有問題。`params` 列出宣告的參數。

把 `on_bar` 改名為 `on_bar_typo`，並把第 6 行的 `WINDOW` 拼錯成 `WINDW` 後：

```json
{"ok": false, "diagnostics": [
  {"message": "a strategy needs a function called on_bar(bar, account)", "line": 1, "offset": 1, "severity": "error"},
  {"message": "WINDW is not defined. It is not part of the strategy API and nothing in this file sets it.", "line": 6, "offset": 1, "severity": "error"}
], "params": []}
```

每筆診斷都標明行號和錯誤內容，在執行前就能發現，不必等到執行的第一根 K 棒才出錯。

!!! danger "策略檔就是一般的 Python"
    檢查或執行策略都會執行這個檔案，沒有沙盒隔離：只執行你信任的策略檔。

## 或者從範本開始

`strategy-tool` 可產生完整的起始檔案：

```sh
uv run strategy-tool templates
```

列出可用的種類：

| 種類 | 策略 |
|---|---|
| `bb` | 布林通道均值回歸（同上） |
| `dca` | 定期定額：每月買固定金額，不賣出 |
| `adx` | 盤勢切換：趨勢盤做突破，其餘做區間 |
| `blank` | 空的 `on_bar` |

寫成檔案（工具輸出 JSON，第二個指令取出其中的 `source` 欄位）：

```sh
uv run strategy-tool template --kind dca \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > dca.py
```

## 策略可以用哪些東西

`bar`：目前的 K 棒及其歷史：

| 名稱 | 內容 |
|---|---|
| `bar.close`、`bar.open`、`bar.volume`、`bar.time` | 這根 K 棒的值 |
| `bar.closes` | 至今所有收盤價，最舊的在前 |
| `bar.ago(n)` | `n` 根 K 棒前的收盤價 |
| `bar.bars_seen` | 這個策略已看過的 K 棒數 |
| `bar.day_high`、`bar.day_low` | **當日至今**的最高價和最低價（不是這根 K 棒的） |

`account`：這個策略自己的現金和持股：

| 名稱 | 內容 |
|---|---|
| `account.cash` | 這個策略可用的現金 |
| `account.equity` | 現金加持股市值 |
| `account.shares`、`account.avg_cost` | 持有股數和平均成本 |
| `account.holding` | 有持股時為 `True` |

決策：

| 呼叫 | 意思 |
|---|---|
| `buy()` | 買到風控額度上限 |
| `buy(100)` | 買進 100 股 |
| `buy(amount=10_000)` | 買進約 NT$10,000，以整股計 |
| `buy(price=250.0)` | 以限價 250 下單，而非這根 K 棒的收盤價 |
| `sell()` | 賣出這個策略的全部持股 |
| `hold("原因")` | 不動作；原因顯示在 bot 的狀態裡 |

工具：

| 名稱 | 用途 |
|---|---|
| `ta.bb`、`ta.sma`、`ta.ema`、`ta.rsi`、`ta.macd`、`ta.wma`、`ta.highest`、`ta.lowest`、`ta.efficiency` | 技術指標；回傳最新值，暖機完成前回傳 `None` |
| `param.int`、`param.float`、`param.bool`、`param.choice` | 宣告可調參數 |
| `state.x = ...` | 跨 K 棒保存值 |
| `watch(name=value)` | 在 bot 的狀態裡顯示數值 |
| `plot(name=value)` | 在圖上畫線 |

選用的 hook：`init()` 在第一根 K 棒前執行一次，`on_fill(fill, account)` 在每次成交後執行，`on_end(account)` 在最後一根 K 棒後執行。

`uv run strategy-tool api` 列出每個名稱及其完整簽名。

!!! warning "時間長度是用 K 棒數算的，不是天數"
    `ta.bb(bar.closes, 20)` 是 20 *根 K 棒*：日 K 上是 20 個交易日，1 分 K 上是 20 分鐘。同一個檔案換成其他 K 棒週期，行為等同另一個策略。

!!! warning "目前的限制"
    - `bar` 只保留收盤價歷史，因此需要每根 K 棒最高價和最低價的 `ta.adx`、`ta.atr`、`ta.stoch` 無法在策略檔中使用。
    - `param.*` 目前一律回傳宣告的預設值。要改值請修改檔案。

下一步：[回測](backtesting.md)。
