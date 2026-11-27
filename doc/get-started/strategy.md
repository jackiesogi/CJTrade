# Write a strategy

In this page you write a strategy file, check it for mistakes, and see what
each part does. In the next page you run it over a year of prices.

## What a strategy is

A strategy is a Python file with one required function, `on_bar`. CJTrade
calls it once for every new bar, and it answers with one of three things:

- `buy(...)`: I want to buy,
- `sell(...)`: I want to sell,
- `hold("why")`: do nothing this time, for this reason.

The file never talks to a broker. `buy()` only states an *intention*; the
backtester or the trading engine decides whether the order is placed, how
big it is, and sends it. That is why the same file runs unchanged in a
backtest, on ArenaX and on a real account.

## Your first strategy

This is a *Bollinger band* strategy. Bollinger bands are a line above and a
line below the recent average price. The idea: when the price drops to the
lower line it is "cheap", so buy; when it reaches the upper line it is
"expensive", so sell.

Save it as `my_strategy.py`:

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

Line by line:

- **Line 1** imports everything a strategy may use: `ta`, `buy`, `sell`,
  `hold`, `param` and the rest. You need no other import.
- **Line 3** declares a *parameter*: a number you may want to tune. Here it
  is 20, the number of bars the bands are calculated over. The label and
  range are used when a tool shows the parameter as a form field.
- **Line 5** is the function CJTrade calls on every bar. `bar` is the newest
  bar plus the history before it; `account` is this strategy's money and
  shares.
- **Line 6** calculates the bands from the closing prices so far
  (`bar.closes`). Inside a strategy, `ta.bb` returns just the **latest**
  three values, not whole arrays.
- **Lines 7-8**: until there are 20 bars, there are no bands yet and `ta.bb`
  returns `None`. The strategy waits and says why.
- **Line 10** `watch(...)` records numbers to show while the bot runs. It
  does not affect trading.
- **Lines 12-15** are the rules. `account.holding` is true when this strategy
  owns shares, so it never buys twice in a row or sells what it does not
  have.
- **Line 16**: in every other case, do nothing.

## Check it before running it

`strategy-tool check` reads the file and reports mistakes without running
any trades:

```sh
uv run strategy-tool check < my_strategy.py
```

Expected output:

```json
{"ok": true, "diagnostics": [], "params": [{"kind": "int", "default": 20, "label": "Bollinger window", "min": 5, "max": 500}]}
```

`"ok": true` and an empty `diagnostics` list mean no problems were found.
`params` lists the parameters the file declares.

Now break it on purpose: rename `on_bar` to `on_bar_typo` and misspell
`WINDOW` as `WINDW` on line 6, then check again:

```json
{"ok": false, "diagnostics": [
  {"message": "a strategy needs a function called on_bar(bar, account)", "line": 1, "offset": 1, "severity": "error"},
  {"message": "WINDW is not defined. It is not part of the strategy API and nothing in this file sets it.", "line": 6, "offset": 1, "severity": "error"}
], "params": []}
```

Each diagnostic gives the line and what is wrong. Catching this now is
better than finding out on the first bar of a long run.

!!! danger "A strategy file is ordinary Python"
    Checking or running a strategy executes the file. It is not a sandbox:
    only run strategy files you trust.

## Start from a template instead

`strategy-tool` can write a complete starting file for you:

```sh
uv run strategy-tool templates
```

lists the kinds:

| Kind | Strategy |
|---|---|
| `bb` | Bollinger mean reversion (like the one above) |
| `dca` | Dollar-cost averaging: buy a fixed amount every month, never sell |
| `adx` | Regime switch: trade breakouts in a trend, the range otherwise |
| `blank` | An empty `on_bar` to fill in |

To save one as a file (the tool prints JSON, and the second command takes
the `source` field out of it):

```sh
uv run strategy-tool template --kind dca \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > dca.py
```

## What a strategy can use

`bar`, the bar being processed and the history before it:

| Name | Value |
|---|---|
| `bar.close`, `bar.open`, `bar.volume`, `bar.time` | this bar's values |
| `bar.closes` | every close so far, oldest first |
| `bar.ago(n)` | the close `n` bars ago |
| `bar.bars_seen` | how many bars this strategy has seen |
| `bar.day_high`, `bar.day_low` | the **trading day's** high and low so far (not this bar's) |

`account`, this strategy's own money and shares:

| Name | Value |
|---|---|
| `account.cash` | cash available to this strategy |
| `account.equity` | cash plus the value of its shares |
| `account.shares`, `account.avg_cost` | shares held and their average cost |
| `account.holding` | `True` if it holds any shares |

Decisions:

| Call | Meaning |
|---|---|
| `buy()` | buy as much as the risk budget allows |
| `buy(100)` | buy exactly 100 shares |
| `buy(amount=10_000)` | buy about NT$10,000 worth, in whole shares |
| `buy(price=250.0)` | limit price 250 instead of the bar's close |
| `sell()` | sell every share this strategy holds |
| `hold("why")` | do nothing; the reason shows in the bot's status |

Tools:

| Name | Use |
|---|---|
| `ta.bb`, `ta.sma`, `ta.ema`, `ta.rsi`, `ta.macd`, `ta.wma`, `ta.highest`, `ta.lowest`, `ta.efficiency` | indicators; each returns the latest value, or `None` until there are enough bars |
| `param.int`, `param.float`, `param.bool`, `param.choice` | declare a tunable value |
| `state.x = ...` | keep a value from one bar to the next |
| `watch(name=value)` | show a number in the bot's status |
| `plot(name=value)` | draw a line on the chart |

Optional functions: `init()` runs once before the first bar,
`on_fill(fill, account)` after each fill, `on_end(account)` after the last
bar.

`uv run strategy-tool api` prints every name with its full signature.

!!! warning "Windows are counted in bars, not days"
    `ta.bb(bar.closes, 20)` is 20 *bars*: 20 trading days on daily bars, 20
    minutes on 1-minute bars. The same file on another interval is a
    different strategy.

!!! warning "Current limitations"
    - `bar` keeps a history of closes only, so `ta.adx`, `ta.atr` and
      `ta.stoch`, which need each bar's high and low, are not available in a
      strategy file.
    - `param.*` always returns the declared default for now. Edit the file
      to change a value.

Next: [Backtesting](backtesting.md).
