# CJTrade

The trading app: one master process holds the broker session and the risk
gate, and runs each strategy as a bot in its own process. Every bar the master
publishes each watched symbol's closed 1m bars to its bots, places the orders
they ask for, and reports the fills back.

Today the broker is ArenaX (backtest, demo, paper or real backend). Start one
first, then the app:

<!-- cjcheck: static -->
```sh
uv run arenaxd --backend=backtest --port=8802 > /dev/null 2>&1 &
uv run cjtrade --broker=arenax --mode=backtest --watch-list=2357 \
  --fund=1000000 --days=30 --start-date=2025-09-01 --speed=0
```

Any field not given on the command line is asked for interactively
(`form.toml`); the answers are remembered for next time.

| Flag | Meaning |
|---|---|
| `--broker` | `arenax` |
| `--mode` | ArenaX backend: `backtest`, `demo`, `paper` |
| `--watch-list` | Symbols to publish, comma-separated |
| `--fund` | The balance bots size against; start `arenaxd` with `AX_INITIAL_BALANCE` set to the same |
| `--days` | Replay length; the window is `[start, start + days)` |
| `--start-date` | First replayed day; blank keeps the server's own |
| `--speed` | Market seconds per real second within a session; `0` is flat out |
| `--roster=FILE` | Which bots to run, instead of `BOT_ROSTER` in `main.py` |

A roster file lists bots by script and symbol; `bot_custom.py` runs a
strategy file written with `cjtrade.pkgs.strategy.authoring`:

<!-- cjcheck: skip reason="a roster file, not a command" -->
```json
[{"bot_id": "Bot_U", "script": "bot_custom.py", "symbol": "2357",
  "extra": ["/absolute/path/to/my_strategy.py"]}]
```

While a run is in progress, `http://127.0.0.1:8898/status` serves its state,
loopback only. When the run was started with `CJ_ENGINE_CONTROL_TOKEN` set
(FinHub always sets one), every request needs that token; without one, reads
are open and the one write, stopping a bot, is refused. [FinHub](../FinHub/README.md) is the web UI on top of
it, and can start runs itself.
