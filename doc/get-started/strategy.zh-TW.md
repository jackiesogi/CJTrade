# 撰寫策略

策略是一個 Python 檔，只 import 一個模組 `cjtrade.pkgs.strategy.authoring`，並定義
`on_bar(bar, account)`。這個檔案完全不碰券商：`buy()` 和 `sell()` 只回傳下單意圖，
由 engine 決定要不要下、怎麼下。同一個檔案可以在
[trading engine](https://github.com/jackiesogi/CJTrade#trading-engine) 和
oneshot [回測](backtesting.md)裡執行。

## 從範本開始

```sh
uv run strategy-tool templates                 # 列出有哪些範本
uv run strategy-tool template --kind bb        # JSON：{"kind": ..., "source": ...}
```

範本種類有 `bb`（布林通道均值回歸）、`dca`（每月定期定額）、`adx`（盤勢切換）和
`blank`。寫成檔案：

```sh
uv run strategy-tool template --kind bb \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > my_strategy.py
```

## 檔案的結構

```python
from cjtrade.pkgs.strategy.authoring import *

WINDOW = param.int(100, "Bollinger window", min=5, max=500)

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

`init()`、`on_fill(fill, account)` 和 `on_end(account)` 都可以不寫。

| 名稱 | 內容 |
|---|---|
| `bar` | `.close` `.open` `.volume` `.time` `.closes` `.ago(n)` `.bars_seen` `.day_high` `.day_low` |
| `account` | `.cash` `.equity` `.shares` `.avg_cost` `.holding`；股數和成本只算這個策略自己的 |
| `ta` | `.bb` `.sma` `.ema` `.rsi` `.macd` `.wma` `.highest` `.lowest` `.efficiency`；每個都回傳**最新一個值**，K 棒數不夠時回傳 `None` |
| `buy()` / `sell()` | `buy()` 買到風控額度允許的上限；`buy(100)` 或 `buy(amount=10000)`；`sell()` 賣出這個策略持有的全部 |
| `hold("原因")` | 不動作，並說明原因；原因會顯示在 bot 的狀態裡 |
| `watch(...)` / `plot(...)` | 要顯示的數值、要畫在圖上的線 |
| `state.x` | 跨 K 棒保留的值 |
| `param.int/float/bool/choice` | 可調參數，會顯示成表單欄位 |

`uv run strategy-tool api` 會列出所有名稱和它們的簽名。

!!! warning "窗口長度以 K 棒數計算"
    `ta.bb(bar.closes, 100)` 是 100 根 K 棒：在 1m 是 100 分鐘，在 1d 是 100 個交易日。
    換 interval 就等於換了一個策略。

!!! warning "`bar.day_high` 和 `bar.day_low` 是當天的，不是這根 K 棒的"
    它們是當天到這根 K 棒為止的最高價和最低價。`bar.open`、`bar.close` 和 `bar.volume`
    則是這根 K 棒自己的值。`bar` 只保留收盤價的歷史，所以需要每根 K 棒高低點的
    `ta.adx`、`ta.atr` 和 `ta.stoch` 刻意不提供。

!!! warning "參數目前無法覆寫"
    `param.*` 永遠回傳宣告時的預設值。要改值請直接改檔案。

## 執行前先檢查

```sh
uv run strategy-tool check < my_strategy.py
```

它會輸出 JSON，包含 `ok`、`diagnostics`（行號、訊息、嚴重程度）以及宣告的
`params`。未定義的名稱和缺少 `on_bar` 都會在這裡抓到，不用等到第一根 K 棒。

!!! danger "策略檔就是一般的 Python"
    載入策略（包括 `check`）時會用完整的 builtins 執行這個檔案，它不是沙盒。只執行
    你信任的檔案。

## 在 trading engine 裡執行

engine 會啟動 roster 裡列出的 bot。`bot_custom.py` 負責執行策略檔，把檔案路徑放在
`extra`：

```json
[
  {"bot_id": "Bot_U", "script": "bot_custom.py", "symbol": "2357",
   "extra": ["/absolute/path/to/my_strategy.py"]}
]
```

然後在 [README](https://github.com/jackiesogi/CJTrade#trading-engine) 的 engine 指令
加上 `--roster=/path/to/roster.json`，並把 bot 的股票代號放進 `--watch-list`。


下一步：[回測](backtesting.md)。
