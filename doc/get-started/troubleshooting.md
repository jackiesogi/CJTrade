# Troubleshooting

Common failures, their cause, and the fix.

## Connecting

??? question "`connect()` fails with `Connection refused`"
    Nothing is listening on the port the client uses. Check:

    - `uv run arenaxd` is running and has printed `sim env started`.
    - Server and client use the same port. `arenaxd` listens on 8801 for
      `demo`, 8802 for `backtest` and 8803 for `paper`. `AccountClient`
      connects to 8801 unless `ARENAX_PORT` is set; `cjtrade --mode=...`
      picks the port that matches the mode.

??? question "`Address already in use` when starting a server or the engine"
    Another instance holds the port. Find it with
    `lsof -nP -iTCP:8801 -sTCP:LISTEN` (substitute the port from the
    message) and stop it. The engine also binds 5555, 5556 and 8898, so two
    concurrent engine runs collide.

??? question "The account is back to NT$100,000"
    Every `arenaxd` start creates a fresh simulated account; it lives only as
    long as the server process.

## Prices

??? question "`get_kbars` returns an empty list"
    - Window is after ArenaX's simulated clock → use dates before
      `client.get_market_time()["mock_current_time"]`.
    - Window has no trading days (weekend or holiday).
    - End date is exclusive: `start="2025-09-01", end="2025-09-01"`
      is an empty window.
    - Server runs with `--data=offline` and the file lacks that symbol,
      interval or day → preload it with `preload-prices`.

??? question "`UnsupportedRequest`"
    The source cannot serve that interval at all (e.g. 1-minute bars from
    FinMind without a paid plan) → chain another source behind it with
    `Fallback`, as in [Market data](market-data.md#without-a-broker-free-sources).

??? question "No minute bars from Yahoo for an older period"
    Yahoo keeps only about the last 30 days of 1-minute bars. Older minute
    bars require Sinopac or a FinMind paid plan.

??? question "`[ERROR] yfinance: ... possibly delisted`"
    Yahoo returned nothing for one of the requested days (often a weekend).
    Harmless if the program continues.

## Orders

??? question "My order stays at `COMMITTED_WAIT_MATCHING`"
    The limit has not been reached: a buy fills when the market trades down
    to the limit, a sell when it trades up to it. On ArenaX the simulated
    clock must also advance, since orders are matched against subsequent
    bars.

??? question "My order is `REJECTED`"
    The reason is in `result.message`. Typical causes: insufficient cash,
    selling more shares than held, a price far from the market, or a
    quantity that does not fit the lot type.

??? question "ArenaX filled my buy at a price higher than the market"
    ArenaX books fills at the limit price → place limits near the market for
    realistic costs. See
    [Account and orders](account-and-orders.md#buy-one-share).

## Strategies and the engine

??? question "`strategy-tool check` says a name is not defined"
    The name is neither in the strategy vocabulary nor assigned in the file,
    usually a typo. `uv run strategy-tool api` lists every valid name.

??? question "My strategy never trades"
    - Still warming up: a 20-bar indicator has no value until 20 bars have
      passed. Check the `hold(...)` reasons in the bot's status.
    - In the engine, the bot's symbol is missing from `--watch-list`.

??? question "The engine warns `broker balance 100000 != requested fund=1000000`"
    The ArenaX account started with the default NT$100,000 → start
    `arenaxd` with `AX_INITIAL_BALANCE=1000000` to match `--fund`.

??? question "The engine says the server does not have prices for the replay"
    The server loaded fewer days than the replay needs → preload a longer
    window, or start `arenaxd` with a larger `AX_BACKTEST_DURATION_DAYS`
    (days loaded, counted from the start date).

## Reporting a problem

Open an issue at <https://github.com/jackiesogi/CJTrade/issues> with the
command you ran and its full output.
