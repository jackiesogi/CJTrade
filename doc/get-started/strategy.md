# Write a strategy

This page covers writing a strategy file, checking it statically, and the
strategy API. The next page backtests it over a year of prices.

## What a strategy is

A strategy is a Python file with one required function, `on_bar`. CJTrade
calls it once per new bar, and it returns one of:

- `buy(...)`: intent to buy,
- `sell(...)`: intent to sell,
- `hold("why")`: no action this bar, with a reason.

The file never talks to a broker. `buy()` expresses intent only; the
backtester or the trading engine decides whether to place the order, sizes
it, and sends it. The same file therefore runs unchanged in a backtest, on
ArenaX and on a real account.

## Your first strategy

A Bollinger band mean-reversion strategy: buy on a lower-band touch, sell
on an upper-band touch. Save it as `my_strategy.py`:

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

| Line | Notes |
|---|---|
| 1 | The star import provides the whole strategy vocabulary (`ta`, `buy`, `sell`, `hold`, `param`, ...). No other import is needed. |
| 3 | `param.int(default, label, min=, max=)` declares a tunable parameter, here the band window of 20 bars. Label and range are used when a tool renders it as a form field. |
| 5 | `on_bar` is called once per bar. `bar` is the newest bar plus its history; `account` is this strategy's cash and shares. |
| 6 | Bands over `bar.closes`. Inside a strategy, `ta.bb` returns only the **latest** three values, not arrays. |
| 7-8 | `ta.bb` returns `None` until 20 bars are available; the strategy holds with the reason. The `hold` reason is shown in the bot's status. |
| 10 | `watch(...)` records values for display while the bot runs. Display only; it does not affect trading. |
| 12-15 | Entry and exit rules. `account.holding` is per-strategy (true when this strategy holds shares), so it never buys twice in a row or sells shares it does not have. |
| 16 | Otherwise, hold. |

## Check it before running it

`strategy-tool check` reports errors without running any trades:

```sh
uv run strategy-tool check < my_strategy.py
```

Expected output:

```json
{"ok": true, "diagnostics": [], "params": [{"kind": "int", "default": 20, "label": "Bollinger window", "min": 5, "max": 500}]}
```

`"ok": true` with an empty `diagnostics` list means no problems. `params`
lists the declared parameters.

With `on_bar` renamed to `on_bar_typo` and `WINDOW` misspelled as `WINDW`
on line 6:

```json
{"ok": false, "diagnostics": [
  {"message": "a strategy needs a function called on_bar(bar, account)", "line": 1, "offset": 1, "severity": "error"},
  {"message": "WINDW is not defined. It is not part of the strategy API and nothing in this file sets it.", "line": 6, "offset": 1, "severity": "error"}
], "params": []}
```

Each diagnostic carries the line and the error, so these are caught before
a run rather than on its first bar.

!!! danger "A strategy file is ordinary Python"
    Checking or running a strategy executes the file. There is no sandbox:
    run only strategy files you trust.

## Start from a template instead

`strategy-tool` generates complete starter files:

```sh
uv run strategy-tool templates
```

lists the available kinds:

| Kind | Strategy |
|---|---|
| `bb` | Bollinger mean reversion (as above) |
| `dca` | Dollar-cost averaging: fixed amount every month, never sells |
| `adx` | Regime switch: breakouts in a trend, range trading otherwise |
| `blank` | Empty `on_bar` |

To write one to a file (the tool prints JSON; the second command extracts
the `source` field):

```sh
uv run strategy-tool template --kind dca \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > dca.py
```

## What a strategy can use

`bar`, the current bar and its history:

| Name | Value |
|---|---|
| `bar.close`, `bar.open`, `bar.volume`, `bar.time` | this bar's values |
| `bar.closes` | all closes so far, oldest first |
| `bar.ago(n)` | close `n` bars ago |
| `bar.bars_seen` | number of bars this strategy has seen |
| `bar.day_high`, `bar.day_low` | **session-to-date** high and low (not this bar's) |

`account`, this strategy's own cash and shares:

| Name | Value |
|---|---|
| `account.cash` | cash available to this strategy |
| `account.equity` | cash plus market value of its shares |
| `account.shares`, `account.avg_cost` | shares held and average cost |
| `account.holding` | `True` if it holds any shares |

Decisions:

| Call | Meaning |
|---|---|
| `buy()` | buy up to the risk budget |
| `buy(100)` | buy exactly 100 shares |
| `buy(amount=10_000)` | buy about NT$10,000, rounded to whole shares |
| `buy(price=250.0)` | limit price 250 instead of the bar's close |
| `sell()` | sell all shares this strategy holds |
| `hold("why")` | no action; the reason shows in the bot's status |

Tools:

| Name | Use |
|---|---|
| `ta.bb`, `ta.sma`, `ta.ema`, `ta.rsi`, `ta.macd`, `ta.wma`, `ta.highest`, `ta.lowest`, `ta.efficiency` | indicators; each returns the latest value, or `None` until warm |
| `param.int`, `param.float`, `param.bool`, `param.choice` | declare a tunable value |
| `state.x = ...` | persist a value across bars |
| `watch(name=value)` | show a value in the bot's status |
| `plot(name=value)` | plot a line on the chart |

Optional hooks: `init()` runs once before the first bar,
`on_fill(fill, account)` after each fill, `on_end(account)` after the last
bar.

`uv run strategy-tool api` prints every name with its full signature.

!!! warning "Windows are counted in bars, not days"
    `ta.bb(bar.closes, 20)` is 20 *bars*: 20 trading days on daily bars, 20
    minutes on 1-minute bars. The same file on another interval behaves as
    a different strategy.

!!! warning "Current limitations"
    - `bar` keeps close history only, so `ta.adx`, `ta.atr` and `ta.stoch`,
      which need per-bar high and low, are not available in a strategy file.
    - `param.*` currently always returns the declared default. Edit the
      file to change a value.

Next: [Backtesting](backtesting.md).
