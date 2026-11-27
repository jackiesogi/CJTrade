# Troubleshooting

Common problems, what causes them, and what to do.

## Connecting

??? question "`connect()` fails with `Connection refused`"
    Nothing is listening where the client looks. Check that:

    - `uv run arenaxd` is running in another terminal and has printed
      `sim env started`;
    - the server and the client agree on the port. `arenaxd` uses 8801 for
      `demo`, 8802 for `backtest` and 8803 for `paper`; `AccountClient` uses
      8801 unless you set `ARENAX_PORT`, and `cjtrade --mode=...` picks the
      port that matches the mode.

??? question "`Address already in use` when starting a server or the engine"
    Another copy is still running. Find it with
    `lsof -nP -iTCP:8801 -sTCP:LISTEN` (use the port from the message), and
    stop that process. The engine also uses ports 5555, 5556 and 8898, so two
    engine runs at the same time collide.

??? question "The account is back to NT$100,000"
    Each start of `arenaxd` opens a fresh pretend account. The account lasts
    as long as the server keeps running.

## Prices

??? question "`get_kbars` returns an empty list"
    - The window is in the future of ArenaX's simulated clock. Use dates
      before `client.get_market_time()["mock_current_time"]`.
    - The window has no trading: a weekend or a holiday.
    - The end date is not included: `start="2025-09-01", end="2025-09-01"`
      is an empty window.
    - The server runs with `--data=offline` and the file does not have that
      symbol, interval or day. Preload it with `preload-prices`.

??? question "`UnsupportedRequest`"
    The source cannot serve that interval at all, for example 1-minute bars
    from FinMind without a paid plan. Put another source behind it with
    `Fallback`, as in [Market data](market-data.md#without-a-broker-free-sources).

??? question "No minute bars from Yahoo for an older period"
    Yahoo keeps only about the last 30 days of 1-minute bars. For older
    minute bars you need Sinopac, or a FinMind paid plan.

??? question "`[ERROR] yfinance: ... possibly delisted`"
    Yahoo had nothing for one of the days asked about (often a weekend).
    It is noise as long as the program carries on.

## Orders

??? question "My order stays at `COMMITTED_WAIT_MATCHING`"
    The price has not been reached. A buy fills when the market comes down
    to your limit, a sell when it comes up to it. On ArenaX, time also has to
    move on: the order is matched against the next bars.

??? question "My order is `REJECTED`"
    Read `result.message`. The usual reasons are not enough cash, selling
    more shares than you hold, a price far from the market, or a quantity
    that does not fit the lot type.

??? question "ArenaX filled my buy at a price higher than the market"
    ArenaX books a fill at your limit price. Place limits close to the
    market for realistic costs. See
    [Account and orders](account-and-orders.md#buy-one-share).

## Strategies and the engine

??? question "`strategy-tool check` says a name is not defined"
    The name is neither part of the strategy vocabulary nor set in your
    file, usually a typo. `uv run strategy-tool api` lists every name you
    can use.

??? question "My strategy never trades"
    - It may still be warming up: an indicator over 20 bars has no value
      until 20 bars have passed. Look at the `hold(...)` reasons in the bot's
      status.
    - In the engine, the bot's symbol must be in `--watch-list`.

??? question "The engine warns `broker balance 100000 != requested fund=1000000`"
    The ArenaX account started with the default NT$100,000. Start `arenaxd`
    with `AX_INITIAL_BALANCE=1000000` so the account matches `--fund`.

??? question "The engine says the server does not have prices for the replay"
    The server loaded fewer days than you asked to replay. Preload a longer
    window, or start `arenaxd` with a larger `AX_BACKTEST_DURATION_DAYS`
    (the number of days it loads, counted from the start date).

## Still stuck

Open an issue at <https://github.com/jackiesogi/CJTrade/issues> with the
command you ran and the full output.
