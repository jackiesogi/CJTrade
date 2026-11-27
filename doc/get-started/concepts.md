# Key ideas

Conventions and terms used throughout these pages.

## Conventions used in CJTrade

| Term | CJTrade convention |
|---|---|
| Symbol (股票代號) | Bare exchange code: `2330` (TSMC), `0050` (Yuanta Taiwan 50 ETF). Never `2330.TW`. |
| Broker (券商) | Anything that accepts orders: the simulated broker **ArenaX**, or a real broker, **Sinopac**, **Fubon** or **Yuanta**, each behind its own adapter. |
| Order (委託) | A request. Placing it does not mean it filled. |
| Fill (成交) | Only fills change cash and positions. |
| Limit price (限價) | A limit order the market never reaches stays open. |
| Lot / odd lot (整張 / 零股) | One lot is 1,000 shares. The order shortcuts trade odd lots by default, so `quantity=1` is one share, which keeps examples cheap. |
| ROD, IOC, FOK | **ROD** (Rest of Day, 當日有效) is the default and stays open until the end of the trading day. IOC and FOK fill immediately or are cancelled. |
| Position (庫存) | Shares held in one symbol, with average cost. |
| Balance (餘額) | Cash, in NT$. |
| Trading session (交易時段) | TWSE, 09:00 to 13:30, Monday to Friday, except holidays. |
| Commission and tax (手續費 / 證交稅) | Commission 0.1425% of fill value, minimum NT$20, on every fill. Transaction tax on sells: 0.3% for stocks, 0.1% for ETFs (symbols starting with `0`). Both are charged on every simulated fill. |
| Bar, K-bar (K 棒) | Open, high, low, close, volume. Volume is in lots. Intraday bars are stamped at the minute they close; daily bars are stamped 09:00. |
| Interval | `1m`, `5m`, `15m`, `30m`, `1h` or `1d` (one trading day). |
| Snapshot (即時報價) | Latest quote: last price, the day's open, high and low so far, best bid and ask. |
| Indicator (技術指標) | Computed with TA-Lib (moving averages, Bollinger bands, ...). |
| Market data source | Sinopac (account required), FinMind and Yahoo Finance (free), or a local price file. |

## CJTrade terms

**ArenaX**
:   The simulated broker bundled with CJTrade, a local server started with
    `uv run arenaxd`. It keeps its own cash and positions, accepts orders,
    and fills them against real historical prices. It has four modes,
    called *backends*:

    | Backend | Prices | Orders go to | Use it for |
    |---|---|---|---|
    | `demo` (default) | Yahoo Finance, the last few weeks | ArenaX | trying things out |
    | `backtest` | Sinopac, or any source you choose | ArenaX | replaying a chosen period |
    | `paper` | Sinopac, live | ArenaX | paper trading during market hours |
    | `real` | Sinopac, live | **your real Sinopac account** | real trading through ArenaX |

**Simulated clock**
:   ArenaX does not run on today's date. It starts on a day in the past and
    plays the market forward faster than real time (120× in `demo`),
    skipping nights and weekends. "Now" always means ArenaX's simulated now.

**AccountClient**
:   The single Python object for every broker: balance, orders, prices.

**Strategy**
:   A Python file with an `on_bar` function. CJTrade calls it once per bar;
    it returns buy, sell or hold.

**Backtest**
:   A strategy run over historical prices. The *oneshot* backtest, the
    fastest kind, runs entirely in memory and finishes in seconds.

**Trading engine (`cjtrade`)**
:   Runs strategies as they would run live: minute by minute, each strategy
    in its own process (a *bot*), with every order routed through one
    checkpoint before it reaches the broker.

**Bot**
:   One strategy running inside the trading engine, on one symbol.

**Risk gate**
:   The engine's checks on every order before it reaches the broker: a
    capital budget per bot, a maximum number of orders per bar, and a stop
    when the account loses too much.

**Round trip**
:   A buy and the sell that closes it. Reports count wins and losses per
    round trip.

Next: [Connect to a broker](connect.md).
