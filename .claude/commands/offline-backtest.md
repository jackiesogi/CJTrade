---
description: Replay the trading engine offline on a preloaded price file
argument-hint: <symbols e.g. 2357,2330> <start YYYY-MM-DD> <days>
---
Run a trading-engine backtest with no network, on bars already on disk.
Arguments: $ARGUMENTS (symbols, start date, number of days).

1. Use the shared price cache (`uv run python -c "from cjtrade.pkgs import paths; print(paths.price_db_path())"`),
   or a file given by the user. If the window may be missing, preload it
   first with `uv run preload-prices --price-db <file> --symbols <symbols> --start <start>`
   (this one step does use the network).
2. Start the server in the background, offline, and wait until
   `curl -s localhost:8802/health` reports `"running":true`:
   `CJTRADE_OFFLINE=1 AX_BACKTEST_DURATION_DAYS=<days + 15> uv run arenaxd --backend=backtest --port=8802 --data=offline --price-db=<file> > /tmp/arenax.log 2>&1 &`
3. Run the engine and keep its log:
   `uv run python poc/trading_engine/main.py --broker=arenax --mode=backtest --watch-list=<symbols> --fund=1000000 --days=<days> --start-date=<start> --speed=0 > /tmp/engine.log 2>&1`
4. Stop the server you started (only that process).
5. Report from /tmp/engine.log: bars replayed, signals per bot, fills, PnL,
   and the round-trip table; and any ERROR/WARNING lines from either log.

The bots trade the symbols in `BOT_ROSTER` in poc/trading_engine/main.py,
which must be in the watch list.
