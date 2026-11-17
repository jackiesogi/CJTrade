# Write a strategy

A strategy is a Python file that imports one module,
`cjtrade.pkgs.strategy.authoring`, and defines `on_bar(bar, account)`. The
file never touches a broker: `buy()` and `sell()` return an intent, and the
engine decides whether and how it is placed. The same file runs in the
[trading engine](https://github.com/jackiesogi/CJTrade#trading-engine) and
in the oneshot [backtester](backtesting.md).

## Start from a template

```sh
uv run strategy-tool templates                 # which templates exist
uv run strategy-tool template --kind bb        # JSON: {"kind": ..., "source": ...}
```

The kinds are `bb` (Bollinger mean reversion), `dca` (monthly
dollar-cost averaging), `adx` (regime switch) and `blank`. To write one to a
file:

```sh
uv run strategy-tool template --kind bb \
  | uv run python -c "import json,sys; print(json.load(sys.stdin)['source'])" > my_strategy.py
```

## The shape of a file

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

`init()`, `on_fill(fill, account)` and `on_end(account)` are optional.

| Name | What it is |
|---|---|
| `bar` | `.close` `.open` `.volume` `.time` `.closes` `.ago(n)` `.bars_seen` `.day_high` `.day_low` |
| `account` | `.cash` `.equity` `.shares` `.avg_cost` `.holding`; shares and cost are this strategy's own |
| `ta` | `.bb` `.sma` `.ema` `.rsi` `.macd` `.wma` `.highest` `.lowest` `.efficiency`; each returns the **latest value**, or `None` until there are enough bars |
| `buy()` / `sell()` | `buy()` buys as much as the risk budget allows; `buy(100)` or `buy(amount=10000)`; `sell()` sells everything this strategy holds |
| `hold("why")` | do nothing, and say why; the reason shows in the bot's status |
| `watch(...)` / `plot(...)` | numbers to display, lines to chart |
| `state.x` | a value that survives from bar to bar |
| `param.int/float/bool/choice` | a tunable value, rendered as a form field |

`uv run strategy-tool api` prints every name with its signature.

!!! warning "Windows are counted in bars"
    `ta.bb(bar.closes, 100)` is 100 bars: 100 minutes on 1m bars, 100
    trading days on 1d bars. Changing the interval changes the strategy.

!!! warning "`bar.day_high` and `bar.day_low` are the day's, not the bar's"
    The engine feeds bars built from snapshots, whose high and low are the
    trading day's so far. For the same reason `ta.adx`, `ta.atr` and
    `ta.stoch` are deliberately not available.

!!! warning "Parameters cannot be overridden yet"
    `param.*` always returns the declared default. Edit the file to change
    a value.

## Check a file before running it

```sh
uv run strategy-tool check < my_strategy.py
```

It prints JSON with `ok`, a list of `diagnostics` (line, message,
severity) and the declared `params`. Undefined names and a missing `on_bar`
are caught here rather than on the first bar.

!!! danger "A strategy file is ordinary Python"
    Loading a strategy (`check` included) executes the file with full
    builtins. It is not a sandbox: only run files you trust.

## Run it in the trading engine

The engine starts the bots listed in a roster. `bot_custom.py` runs a
strategy file; pass the file's path in `extra`:

```json
[
  {"bot_id": "Bot_U", "script": "bot_custom.py", "symbol": "2357",
   "extra": ["/absolute/path/to/my_strategy.py"]}
]
```

Then add `--roster=/path/to/roster.json` to the engine command in the
[README](https://github.com/jackiesogi/CJTrade#trading-engine), with the
bot's symbol in `--watch-list`.

!!! warning
    The trading engine lives in `poc/` and is still a proof of concept.

Next: [Backtesting](backtesting.md).
