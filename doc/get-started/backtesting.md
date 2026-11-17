# Backtesting

`BacktestEngine` runs a strategy over a list of bars in memory: no server,
no clock, finished in seconds. Two runs over the same bars give the same
result.

## Get the bars

Any `Kbar` list works. The simplest source is ArenaX (see
[Connect to a broker](connect.md) to start it):

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()
kbars = client.get_kbars(Product("2330"), start="2024-01-01",
                         end="2025-10-01", interval="1d")
client.disconnect()
```

## Run a built-in strategy

```python
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.strategy.bb import BollingerStrategy

engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        params={"bb__window_size": 20})
result = engine.run(BollingerStrategy())
print(result.final_equity, len(result.fill_history))
```

The built-ins are `BollingerStrategy`, `ADXAdaptiveStrategy`,
`DCA_Monthly`, `DonchianBreakoutStrategy`, `SupportResistanceStrategy` and
`BaselineStrategy`; see [Built-in strategies](../reference/strategies.md)
for their parameters.

## Run a strategy file

A file written for [the authoring module](strategy.md) runs the
same way once loaded:

```python
from pathlib import Path
from cjtrade.pkgs.strategy.user_strategy import load

strategy = load(Path("my_strategy.py").read_text())
result = BacktestEngine(kbars=kbars, symbol="2330",
                        initial_balance=1_000_000).run(strategy)
```

## Read the result

```python
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport

report = BacktestReport(result)
report.summary()              # key numbers to stdout
report.print_round_trips()    # every entry and exit
print(report.metrics())       # the same as a dict
report.save_html("report.html")
```

Every fill pays the TWSE costs from `CostModel`: 0.1425% commission with a
NT$20 minimum, and 0.3% transaction tax on sells (0.1% for symbols starting
with `0`). Pass `cost_model=CostModel(...)` to change the discount or add
slippage.

!!! warning "Fills are optimistic"
    A signal computed on a bar's close is filled on the same bar at the
    signal's price, without checking that the price was inside the bar's
    range, without volume limits and without price limits. Treat results as
    an upper bound.

!!! warning "`full_report()` opens a browser"
    `BacktestReport.full_report()` writes an HTML tearsheet and opens it by
    default. Use `save_html(path)`, or `full_report(open_browser=False)`, on
    a machine without one.

For the command-line backtesters (`poc/backtest.sh`, the trading engine) and
`insight`, see the
[README](https://github.com/jackiesogi/CJTrade#backtesting).
