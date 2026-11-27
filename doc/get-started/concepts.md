# Key ideas

These pages use a handful of trading and CJTrade words. Each one is
explained here once, in plain terms, so the rest of the guide can use them.
You can skim this page now and come back when a word is unclear.

## Trading words

**Symbol (股票代號)**
:   The code of a stock on the exchange. `2330` is TSMC, `0050` is the
    Yuanta Taiwan 50 ETF. CJTrade always uses the bare code, never `2330.TW`.

**Broker (券商)**
:   The company that holds your cash and shares and sends your orders to the
    exchange. In CJTrade a broker is anything that accepts orders: the
    pretend broker **ArenaX**, or the real broker **Sinopac**.

**Order (委託)**
:   An instruction to buy or sell: which symbol, how many shares, at what
    price. Placing an order does not mean it happened; it is a request.

**Fill (成交)**
:   An order that actually happened. A buy order *fills* when someone sells
    to you at your price. Only filled orders change your cash and shares.

**Limit price (限價)**
:   The worst price you accept. A buy limit of 1000 means "buy at 1000 or
    cheaper". If the market never comes down to 1000, the order just waits.

**Lot and odd lot (整張 / 零股)**
:   On TWSE one *lot* is 1,000 shares. An *odd-lot* order trades single
    shares. CJTrade's shortcuts trade odd lots by default, so `quantity=1` is
    one share, which keeps examples cheap.

**ROD, IOC, FOK**
:   How long an order stays open. **ROD** (Rest of Day, 當日有效) waits until
    the end of the trading day and is the default. IOC and FOK are filled
    immediately or cancelled.

**Position (庫存)**
:   The shares of one symbol you hold, with the average price you paid.

**Balance (餘額)**
:   Cash in the account, in NT$.

**Trading session (交易時段)**
:   TWSE trades from 09:00 to 13:30, Monday to Friday, except holidays.

**Commission and tax (手續費 / 證交稅)**
:   Every fill pays a commission of 0.1425% of its value (at least NT$20).
    A sell also pays transaction tax: 0.3% for stocks, 0.1% for ETFs (symbols
    starting with `0`). CJTrade charges these on every simulated fill too.

## Price words

**Bar, or K-bar (K 棒)**
:   A summary of the prices during one stretch of time: the first price
    (*open*), the highest (*high*), the lowest (*low*), the last (*close*)
    and how much traded (*volume*). A 1-minute bar summarises one minute.

**Interval**
:   How long each bar is: `1m`, `5m`, `15m`, `30m`, `1h` or `1d` (one trading
    day).

**Snapshot (即時報價)**
:   The latest quote for a symbol: last price, the day's open, high and low
    so far, and the best bid and ask. Unlike a bar, it is "right now".

**Indicator (技術指標)**
:   A number calculated from past prices, such as a moving average or
    Bollinger bands. CJTrade calculates them with TA-Lib.

**Market data source**
:   Where prices come from: Sinopac (needs an account), FinMind and Yahoo
    Finance (free), or a price file on your disk.

## CJTrade words

**ArenaX**
:   The pretend broker that ships with CJTrade. It is a small server that
    you start with `uv run arenaxd`. It has its own cash and positions,
    accepts orders, and fills them against real prices from the past. It
    has four modes, called *backends*:

    | Backend | Prices | Orders go to | Use it for |
    |---|---|---|---|
    | `demo` (default) | Yahoo Finance, the last few weeks | ArenaX | trying things out |
    | `backtest` | Sinopac, or any source you choose | ArenaX | replaying a chosen period |
    | `paper` | Sinopac, live | ArenaX | paper trading during market hours |
    | `real` | Sinopac, live | **your real Sinopac account** | real trading through ArenaX |

**Simulated clock**
:   ArenaX does not use today's date. It picks a day in the past and plays
    the market forward from there, faster than real time (120 times faster
    in `demo`), skipping nights and weekends. "Now" means *ArenaX's* now.

**AccountClient**
:   The one Python object your code uses to talk to any broker: read the
    balance, place an order, get prices.

**Strategy**
:   Your trading rules, written as a Python file with an `on_bar` function.
    CJTrade calls it once per bar, and it answers "buy", "sell" or "hold".

**Backtest**
:   Running a strategy over past prices to see what it would have done. The
    quickest kind, the *oneshot* backtest, runs entirely in memory and
    finishes in seconds.

**Trading engine (`cjtrade`)**
:   The program that runs strategies the way they would run live: minute by
    minute, each strategy in its own process (a *bot*), with all orders
    going through one place that checks them first.

**Bot**
:   One strategy running inside the trading engine, on one symbol.

**Risk gate**
:   The checks the engine applies to every order before it reaches the
    broker: how much money each bot may use, how many orders per bar, and a
    stop if the account loses too much.

**Round trip**
:   One buy followed by the sell that closes it. Reports count wins and
    losses per round trip.

Next: [Connect to a broker](connect.md).
