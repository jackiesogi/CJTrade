# Run the trading engine

The [oneshot backtest](backtesting.md) is quick but simplified. The trading
engine, `cjtrade`, runs strategies the way they would run live: minute by
minute, on ArenaX's clock, with real order matching. In this page you
replay a week of 1-minute prices for one stock, offline, and read the
report.

## What the engine does

```
 cjtrade (main process)
   ├─ holds the one broker connection and the risk gate
   ├─ every minute: sends each bot the newest closed bar
   ├─ waits until every bot has answered, then steps to the next minute
   └─ bots (one process each, one symbol each)
        Bot_B on 2357  ── buy / sell / hold ──▶ main process ──▶ ArenaX
```

- Each strategy runs as a **bot** in its own process, on one symbol.
- Bots never talk to the broker. They answer the main process, which checks
  each order against the **risk gate** (how much money each bot may use, at
  most 3 orders per bar, a stop if the account falls 25%) and only then
  sends it.
- The engine waits for every bot before moving on, so a replay gives the
  same orders every time, however fast it runs.

Which bots run is set by `BOT_ROSTER` in
[`src/cjtrade/apps/CJTrade/main.py`](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/apps/CJTrade/main.py).
By default it is one bot, `Bot_B`, trading `2357` (ASUS) with an ADX regime
strategy. You can replace it with your own file; see
[Run your own strategy](#run-your-own-strategy).

## Step 1: download the prices

Fetch three weeks of 1-minute bars for 2357 into a file. This is the only
step that uses the network:

```sh
uv run preload-prices --price-db prices.db --symbols 2357 --start 2026-11-02 --end 2026-11-21 --interval 1m,1d
```

Pick a window within the last 30 days: the free source for minute bars,
Yahoo Finance, keeps no more than that.

Expected output:

```text
2357 1m: 3639 bars over 15 days (2026-11-02 09:01 .. 2026-11-20 13:25)
2357 1d: 15 bars over 15 days (2026-11-02 09:00 .. 2026-11-20 09:00)
3654 bars in prices.db
```

## Step 2: start ArenaX on that file

In a terminal of its own:

```sh
CJTRADE_OFFLINE=1 AX_INITIAL_BALANCE=1000000 uv run arenaxd --backend=backtest --data=offline --price-db=prices.db
```

| Part | Meaning |
|---|---|
| `CJTRADE_OFFLINE=1` | no network at all; anything that would download fails instead |
| `AX_INITIAL_BALANCE=1000000` | the pretend account starts with NT$1,000,000 (default 100,000) |
| `--backend=backtest` | the replay mode; it listens on port **8802**, which the engine expects |
| `--data=offline --price-db=prices.db` | read prices only from your file |

Wait until it prints `sim env started` (about 20 seconds). A line
`no fetchable history found in 30 attempts` before that is expected: the
server could not choose a start day by itself, and waits for the engine to
tell it.

## Step 3: run the engine

In a second terminal:

```sh
uv run cjtrade --broker=arenax --mode=backtest --watch-list=2357 --fund=1000000 --days=5 --start-date=2026-11-03 --speed=0
```

| Option | Meaning |
|---|---|
| `--broker=arenax` | trade on ArenaX |
| `--mode=backtest` | connect to the `backtest` server on port 8802 (`demo` is 8801, `paper` 8803) |
| `--watch-list=2357` | the symbols to feed; every bot's symbol must be in it |
| `--fund=1000000` | the money the bots size their orders against |
| `--days=5` | how many days to replay |
| `--start-date=2026-11-03` | the first day; leave out for a random day |
| `--speed=0` | as fast as possible; `60` would be one market minute per real second |

!!! tip "Leave options out to be asked"
    Any of these you leave out, the engine asks you for in the terminal,
    with the defaults filled in. Your answers are remembered for next time.

Expected output (shortened):

```text
[INFO][...] engine: broker=arenax backend=backtest clock=replay symbols=2357 fund=1000000 days=5
[INFO][...] engine.clock: replay: 961 bars, 2026-11-03 09:01:00 .. 2026-11-06 13:25:00, flat out (no pacing)
[INFO][...] engine: spawned Bot_B (bot_b.py, 2357)
[INFO][...] bot.Bot_B: started (2357) strategy=ADX_Adaptive
[INFO][...] engine: @2026-11-03 09:34 FILLED BUY 2357 x218/218 px=915.0 for Bot_B (resolved on refresh) balance=800246
[INFO][...] engine: @2026-11-03 10:04 FILLED SELL 2357 x218/218 px=908.0 for Bot_B (resolved on refresh) balance=997314
...
[INFO][...] engine: replay done: 960 bars in 12.6s (76 bars/s)
==================================================
  Backtest Summary
==================================================
  PnL (Total)  :      -76,768.08  (-7.68%)
  Total fills  : 13
  Max drawdown : -7.21%
  Round trips  : 9  (win 0 / loss 9,  win rate 0.0%)
  ...
[INFO][...] engine.report: result saved: .../reports/engine_be329ab8.pkl
HTML saved -> .../reports/engine_be329ab8.html
```

Reading it:

- `replay: 961 bars` is four trading days of 1-minute bars. `--days=5`
  counts calendar days, 3 to 7 November, and the 7th is a Saturday.
- `@2026-11-03 09:34` is the *market* time of the event; the bracket at the
  start of the line is the real time.
- `FILLED BUY 2357 x218/218 px=915.0` means 218 of 218 shares bought at 915.
- The summary has the same lines as the [oneshot report](backtesting.md#read-the-summary).
  This run lost money: the default bot was not suited to that week. That is
  what a backtest is for.
- The result is saved as a `.pkl` file and an HTML report; both paths are
  printed.

While a run is going, its status (bots, positions, recent orders) is at
<http://127.0.0.1:8898/status>.

Stop the ArenaX server with Ctrl+C when you are done.

## Step 4: look into a run with `insight`

`insight` joins a run's result with the prices of the same period and
writes a diagnostic report:

```sh
uv run insight --list      # every run on this machine
uv run insight             # the most recent one
```

Expected output:

```text
1 run(s) in .../reports:
  be329ab8                                 engine   2026-11-27 15:21     40,893 bytes

Run be329ab8 — 13 fill(s), 9 round trip(s), net -76,768.08
  Sharpe -10.754 · Sortino -10.147 · CAGR -99.81% · max drawdown -7.21%
  report  .../reports/engine_be329ab8.insight.md
  json    .../reports/engine_be329ab8.insight.json
```

Open the `.insight.md` file for the full write-up. Over a run this short,
yearly figures such as CAGR are not meaningful.

## Run your own strategy {#run-your-own-strategy}

To run a strategy file from [Write a strategy](strategy.md) as a bot, list it
in a *roster* file, `roster.json`:

```json
[
  {"bot_id": "Bot_U", "script": "bot_custom.py", "symbol": "2357",
   "extra": ["/absolute/path/to/my_strategy.py"]}
]
```

- `bot_id` is any name you like; it appears in the logs.
- `script` is `bot_custom.py`, the bot that runs a strategy file.
- `symbol` is the stock it trades; put it in `--watch-list` too.
- `extra` holds the **absolute** path of your strategy file.

Then add `--roster=roster.json` to the command in step 3.

## Other modes

| `--mode` | ArenaX started with | Clock |
|---|---|---|
| `backtest` | `uv run arenaxd --backend=backtest` | replays a chosen period, as fast as `--speed` |
| `demo` | `uv run arenaxd` | the demo server's own fast-running clock |
| `paper` | `uv run arenaxd --backend=paper` | the real clock, during market hours, with live Sinopac prices |

The [FinHub web UI](shell-and-finhub.md#finhub) starts ArenaX and the engine
for you, and shows the same run in a browser.

Next: [CJShell and FinHub](shell-and-finhub.md).
