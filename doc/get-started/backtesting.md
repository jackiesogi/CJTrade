# Backtesting

A oneshot backtest of a strategy over a year of TSMC (2330) daily bars. It
runs in memory with no server and completes in a few seconds. Its fill
model is optimistic; see
[What a backtest leaves out](#what-a-backtest-leaves-out).

## Run a built-in strategy

The built-in Bollinger band strategy over 2024 with NT$1,000,000:

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.strategy.bb import BollingerStrategy

# 1. Get a year of daily bars from the free sources.
market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))
kbars = market.get_kbars("2330", "2024-01-01", "2025-01-01", "1d")
print("bars:", len(kbars))

# 2. Run the strategy over them.
engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        params={"bb__window_size": 20})
result = engine.run(BollingerStrategy())

# 3. Print the summary and every trade.
report = BacktestReport(result)
report.summary()
report.print_round_trips()
```

- Step 1 is the same as in [Market data](market-data.md).
- `params={"bb__window_size": 20}` sets strategy parameters. Built-in
  strategies use `<group>__<name>` keys; [Built-in strategies](../reference/strategies.md)
  lists them all.
- `engine.run(...)` iterates over the bars, calls the strategy on each, and
  simulates the resulting orders.

Expected output:

```text
bars: 242
==================================================
  Backtest Summary
==================================================
  Session      : N/A
  Start time   : 2024-01-02T09:00:00
  Init balance :    1,000,000.00
  Final balance:    1,016,806.00
  Final equity :    1,016,806.00
  PnL (Total)  :      +16,806.00  (+1.68%)
  rPnL         :      +16,806.00
  uPnL         :           +0.00  (+0.00%)
  Total fills  : 4
  Commission   :          307.65
  Tax (證交稅)  :          350.03
  Total cost   :          657.68
  Equity pts   : 242
  Sharpe ratio : 2.0471  (daily resolution, annualised)
  CAGR         : 1.76%
  Max drawdown : -0.50%
  Round trips  : 2  (win 2 / loss 0,  win rate 100.0%)
  Avg PnL/trip : +8,732.00
  Avg hold days: 38.5
==================================================
================================================================================
  Round-Trip History  (2 trades,  win 2 / loss 0,  total PnL +17,464.00)
================================================================================
    #  Symbol    Entry Date      Entry $  Exit Date        Exit $     Qty         PnL   Days
  ----------------------------------------------------------------------------
    1  2330      2024-04-19       750.00  2024-05-15       839.00      66    +5874.00    26d  🟢
    2  2330      2024-08-05       815.00  2024-09-25      1005.00      61   +11590.00    51d  🟢
================================================================================
```

The backtest is deterministic: the same bars give exactly these numbers.

## Read the summary {#read-the-summary}

| Line | Meaning |
|---|---|
| Init balance / Final balance | cash at start and end |
| Final equity | cash + marked-to-market shares still held |
| PnL (Total) | final equity − init balance, absolute and % |
| rPnL / uPnL | realised (cash change from closed trades) / unrealised (open position) |
| Total fills | filled orders; a round trip counts as two |
| Commission, Tax, Total cost | fees summed over all fills |
| Sharpe ratio | from equity-curve returns, daily resolution, annualised |
| CAGR | annualised from the same returns |
| Max drawdown | largest peak-to-trough decline of the equity curve, % |
| Round trips, win rate | matched buy-then-sell pairs, and the share with positive P&L |

Here the strategy made two round trips, both winners, for +1.68% after
costs. Position sizes were 66 and 61 shares because built-in strategies
size each position at about 5% of the account by default
(`risk__max_position_pct=0.05`), leaving most of the capital in cash. That
is why the profit is small next to the stock's own rise that year.

## Run your own strategy file

A file from [Write a strategy](strategy.md) runs the same way once loaded:

```python
from pathlib import Path
from cjtrade.pkgs.strategy.user_strategy import load

strategy = load(Path("my_strategy.py").read_text())
result = BacktestEngine(kbars=kbars, symbol="2330",
                        initial_balance=1_000_000).run(strategy)

for f in result.fill_history:
    print(f["time"][:10], f["action"], f["quantity"], f["price"], f["reason"])
```

Expected output:

```text
2024-04-19 BUY 66 750.0 lower band touch
2024-05-15 SELL 66 839.0 upper band touch
2024-08-05 BUY 61 815.0 lower band touch
2024-09-25 SELL 61 1005.0 upper band touch
```

`my_strategy.py` implements the same rules, so the trades match the
built-in strategy. `reason` is the text passed to `buy()` and `sell()`.

## Save a full report

```python
report.save_html("report.html")
print(report.metrics()["pnl_pct"])          # every number as a dict
```

`report.html` is a QuantStats tearsheet with equity, drawdown and monthly
return charts. Open it in a browser:

![The top of a tearsheet](https://raw.githubusercontent.com/jackiesogi/CJTrade/master/doc/assets/img/quantstats.png)

`report.full_report()` writes the same file and opens it in a browser; pass
`open_browser=False` on a headless machine.

## Costs

Every fill pays TWSE costs: 0.1425% commission with a NT$20 minimum, and
on sells a 0.3% transaction tax (0.1% for ETFs, i.e. symbols starting with
`0`). For a broker commission discount or slippage, pass a `CostModel`:

```python
from cjtrade.pkgs.models.cost import CostModel

engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        cost_model=CostModel(commission_discount=0.6))   # 六折
```

See [Cost model](../reference/cost-model.md) for every option.

## What a backtest leaves out {#what-a-backtest-leaves-out}

The oneshot backtester trades realism for speed:

- A signal computed on a bar's close fills **on that bar, at that price**,
  whether or not the market would have offered it.
- No volume constraint: any size fills at once.
- TWSE daily price limits (漲跌停) are not applied.

Treat the result as an upper bound. For minute-by-minute simulation with
real order matching, use the [trading engine](trading-engine.md). Its
numbers are usually lower; compare trends between the two, not exact
amounts.

Next: [Run the trading engine](trading-engine.md).
