# CJTrade

CJTrade is a Python framework for trading stocks on the Taiwan Stock Exchange
(TWSE). You write your trading idea once, as a small Python file, and run it
in three ways without changing it:

1. **Against history** (a *backtest*), to see how it would have done.
2. **Against a pretend broker** that runs on your own computer, to watch it
   trade without risking money.
3. **Against a real brokerage account** (Sinopac 永豐金證券), when you trust it.

You do not need a brokerage account to try any of it. Everything in
[Get started](get-started/install.md) runs on your computer with free price
data.

!!! danger "Not investment advice"
    CJTrade can place real orders on a real account, and you are responsible
    for every order it sends. Try a strategy on the pretend broker first, then
    on Sinopac's sandbox, before it touches real money.

## How the pieces fit

```
  your strategy file  ─┐
  (on_bar → buy/sell)  │
                       ▼
               ┌───────────────┐   orders, account    ┌──────────────────────┐
               │  CJTrade code │ ───────────────────▶ │ a broker             │
               │ (AccountClient│ ◀─────────────────── │  · ArenaX (pretend)  │
               │  or the engine)   fills, balance     │  · Sinopac (real)    │
               └───────────────┘                      └──────────────────────┘
                       ▲
                       │ prices (bars, quotes)
               ┌───────────────┐
               │ market data   │  Sinopac · FinMind · Yahoo · a local file
               └───────────────┘
```

- **A broker** is where orders go and where your cash and shares live.
  **ArenaX** is a pretend broker that comes with CJTrade: a small server on
  your computer that accepts orders and fills them against real historical
  prices.
- **Market data** is where prices come from. It is separate from the broker,
  so you can, for example, trade on ArenaX with prices from Yahoo Finance.
- **Your code** talks to a broker through one object, `AccountClient`. The
  same calls work on ArenaX and on Sinopac.

If any of these words is new, [Key ideas](get-started/concepts.md) explains
them in plain terms.

## Choose your path

| You want to | Start here | Time |
|---|---|---|
| Install CJTrade and check it works | [Install](get-started/install.md) | 5 min |
| Learn the words used in these pages | [Key ideas](get-started/concepts.md) | 10 min |
| Place your first (pretend) order from Python | [Connect to a broker](get-started/connect.md), then [Account and orders](get-started/account-and-orders.md) | 15 min |
| Get prices and compute an indicator | [Market data](get-started/market-data.md) | 10 min |
| Write a strategy and test it on a year of prices | [Write a strategy](get-started/strategy.md), then [Backtesting](get-started/backtesting.md) | 20 min |
| Run several bots minute by minute, like live trading | [Run the trading engine](get-started/trading-engine.md) | 15 min |
| Use the interactive shell or the web UI | [CJShell and FinHub](get-started/shell-and-finhub.md) | 10 min |
| Fix an error | [Troubleshooting](get-started/troubleshooting.md) | |

The Get started pages build on each other; read them in order the first
time.

## For people who already know CJTrade

| Look up | Page |
|---|---|
| Every command, its options and ports | [Commands](reference/commands.md) |
| Settings files and environment variables | [Configuration and paths](reference/config.md) |
| A class or function | [API reference](reference/index.md) |

!!! note
    The API is not stable yet; names may change before 1.0.
