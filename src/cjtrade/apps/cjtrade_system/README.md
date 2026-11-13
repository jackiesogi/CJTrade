# CJTrade System

The automated trading system: it watches a list of symbols, runs a strategy
over the prices as they arrive, and places the orders the strategy asks for.

Two modes: `full_simulation` and `oneshot`. Both are usually launched through a
wrapper script, because each needs a running ArenaX server and a form's worth of
parameters before it can start.

For how to install and run either one, see the README in the project root.

---

## :warning: `full_simulation` is being retired

The ArenaX-driven full simulation (`cjtrade_system_arenax.py`, reached through
`uv run system`) is **deprecated for backtesting**. Use the trading engine in
[`poc/trading_engine/`](../../../../poc/trading_engine/) instead. The system
itself stays for now — paper and real runs still go through it, and there the
wall clock is the right clock — but a backtest you intend to quote should come
from the engine.

The reason is reproducibility, and it comes down to who owns the clock.

`full_simulation` replays history by making time move faster: the ArenaX server
advances its own virtual clock at a playback speed (up to 30,000x) while the
system samples prices on a *wall-clock* timer and aggregates them into bars.
That works, and it is genuinely fun to watch, but the bars it produces are an
artefact of the machine. Sample a 30,000x replay from a busy laptop and you get
different bars than from an idle one; how many minutes of market time fall into
one bar depends on how long the previous iteration took. Two runs of the same
configuration do not have to agree, and when they disagree there is nothing in
the result that says why.

The trading engine inverts that. Before the run starts it reads the real bar
timestamps out of the price data and keeps them as a list; logical time is then
nothing but a cursor into that list (`ReplayClock`). One step per bar, and every
step pushes the server's market time to the new value, so the server never
advances on its own. Playback speed becomes pacing and nothing else — it decides
how long the engine *waits* between bars, not which bars exist — and `--speed=0`
runs flat out and still produces exactly the same sequence. The bars are a
property of the data, not of the hardware, so a run can be repeated and two
parameter sets can be compared without wondering whether the difference is real.

The engine is also structured differently: each strategy runs in its own
process and sends order *intents* to a master over ZeroMQ, and the master is
the only thing holding a broker session. So every order passes the same risk
gate, and a misbehaving strategy can waste its own budget and nothing else.

---

## `full_simulation`

Replays historical prices at high playback speed, sampling and aggregating them
into K-bars as it goes, against a fully simulated broker backend doing the order
matching. The closest thing to watching the system trade.

```sh
bash poc/backtest_full_simulation.sh
```

The script fills in a form (`poc/backtest_full_simulation.toml`), generates a
fresh account state, opens a couple of monitoring windows, and then runs
`uv run system`. Every form field has a matching command-line flag, so you can
supply some or all of the answers up front:

```sh
bash poc/backtest_full_simulation.sh \
  --broker=arenax --mode=backtest \
  --watch-list=0050,2317 --fund=1000000 --days=30 --speed=1200
```

## `oneshot`

Fetches every K-bar before the backtest begins and matches orders bar by bar.
No clock, no server-side timing, and it finishes in seconds — which is what
makes it the right tool for sweeping a parameter.

```sh
bash poc/backtest.sh
```

Be aware of one difference when comparing the two: `oneshot` fills a signal in
the bar that produced it, while the engine and `full_simulation` send an order
to a broker and wait for a price to cross its limit. A mean-reversion strategy
will look better under `oneshot` for that reason alone, so the two sets of
numbers are not interchangeable — treat `oneshot` as a screen and the engine as
the verdict. `uv run insight` leads its report with which path produced the run
it is reading.
