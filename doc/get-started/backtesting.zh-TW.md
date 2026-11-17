# 回測

`BacktestEngine` 在記憶體裡用一串 K 棒跑策略：不需要伺服器、沒有時鐘，幾秒內就跑完。
同一組 K 棒跑兩次，結果會完全相同。

## 取得 K 棒

任何 `Kbar` 的 list 都可以。最簡單的來源是 ArenaX（啟動方式見[連線到券商](connect.md)）：

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()
kbars = client.get_kbars(Product("2330"), start="2024-01-01",
                         end="2025-10-01", interval="1d")
client.disconnect()
```

## 跑內建策略

```python
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.strategy.bb import BollingerStrategy

engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        params={"bb__window_size": 20})
result = engine.run(BollingerStrategy())
print(result.final_equity, len(result.fill_history))
```

內建策略有 `BollingerStrategy`、`ADXAdaptiveStrategy`、`DCA_Monthly`、
`DonchianBreakoutStrategy`、`SupportResistanceStrategy` 和 `BaselineStrategy`，
參數見[內建策略](../reference/strategies.md)。

## 跑策略檔

用 [authoring 模組](strategy.md)寫的檔案，載入之後用同樣的方式跑：

```python
from pathlib import Path
from cjtrade.pkgs.strategy.user_strategy import load

strategy = load(Path("my_strategy.py").read_text())
result = BacktestEngine(kbars=kbars, symbol="2330",
                        initial_balance=1_000_000).run(strategy)
```

## 看結果

```python
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport

report = BacktestReport(result)
report.summary()              # 主要數字印到 stdout
report.print_round_trips()    # 每一筆進出場
print(report.metrics())       # 同樣的數字，以 dict 回傳
report.save_html("report.html")
```

每筆成交都會依 `CostModel` 扣台股的交易成本：手續費 0.1425%（最低 20 元），賣出時
證交稅 0.3%（代號以 `0` 開頭的是 0.1%）。傳入 `cost_model=CostModel(...)` 可以改
手續費折扣或加上滑價。

!!! warning "成交結果偏樂觀"
    用某根 K 棒收盤價算出的訊號，會在同一根 K 棒以訊號給的價格成交，不檢查價格是否
    在那根 K 棒的高低點之間，也不考慮成交量和漲跌停。請把結果當成上限看待。

!!! warning "`full_report()` 會開瀏覽器"
    `BacktestReport.full_report()` 會寫出 HTML 報表，預設還會用瀏覽器打開。在沒有
    瀏覽器的機器上，請用 `save_html(path)` 或 `full_report(open_browser=False)`。

命令列的回測工具（`poc/backtest.sh`、trading engine）和 `insight` 請見
[README](https://github.com/jackiesogi/CJTrade#backtesting)。
