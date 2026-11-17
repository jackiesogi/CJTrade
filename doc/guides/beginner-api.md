# Beginner API

`cjtrade.pkgs.api.beginner` is a set of short functions for poking at a
broker from a REPL or a notebook: one global client, one current symbol, and
helpers that print an error and return a fallback instead of raising.

!!! warning "For a REPL, not for a bot"
    `buy()` and `sell()` here place orders through the global client
    immediately. A strategy that should run under the engine's risk gate is
    written against the [authoring module](strategy-authoring.md) instead.

## Connect

```python
from cjtrade.pkgs.api.beginner import *
from cjtrade.pkgs.brokers.account_client import BrokerType

client = create_client(BrokerType.ARENAX)   # needs API_KEY=testkey123 in the environment
set_client(client)
set_current_symbol("2330")
```

`create_client` reads `API_KEY`, `SECRET_KEY`, `CA_CERT_PATH` and
`CA_PASSWORD` from the environment (and from a `.env` file), builds an
`AccountClient` and connects it. ArenaX must be running; see the
[Quickstart](quickstart.md).

!!! warning "Always pass a broker type"
    The default, `BrokerType.MOCK`, no longer exists and fails. If you call
    `buy()` or a query before `set_client()`, the module tries to create that
    default client and fails the same way.

!!! danger "Sinopac is a real account"
    `create_client(BrokerType.SINOPAC)` connects to your real account
    (`simulation=False` is the default here). Pass `simulation=True` for
    Sinopac's sandbox.

## Query

| Function | Alias | Returns | On error |
|---|---|---|---|
| `get_current_price(symbol=None)` | `snapshot_price` | latest close from a snapshot | `None` |
| `get_balance()` | `cash` | cash in TWD | `0.0` |
| `get_total_equity()` | `equity` | cash plus position value | `0.0` |
| `get_positions()` | `positions` | list of `Position` | `[]` |
| `get_kbars(symbol, start, end, interval="1d")` | `kbars` | list of `Kbar` | `None` |
| `get_kbar_series(symbol, start, end, interval="1d")` | `series` | `KbarSeries` | `None` |

```python
print(get_current_price(), cash(), equity())

for p in positions():
    print(p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl)

bars = get_kbars("2330", "2025-09-01", "2025-09-05")
print(bars[0].timestamp, bars[0].close)
```

`start` and `end` are `YYYY-MM-DD`. Intervals are `1m`, `5m`, `1h` and `1d`.

!!! warning "An error looks like an empty answer"
    These functions print the error and return the fallback in the table.
    `0.0` cash or an empty position list can mean the broker could not be
    reached. Only a missing symbol raises (`ValueError`).

## Indicators

`ta` wraps TA-Lib and works on arrays, so use a `KbarSeries`, which carries
`closes`, `opens`, `highs`, `lows` and `volumes` as NumPy arrays:

```python
s = get_kbar_series("2330", "2025-08-01", "2025-09-30")
ema = ta.ema(s.closes, 12)                 # array; ema[-1] is the latest
rsi = ta.rsi(s.closes, 14)
upper, middle, lower = ta.bb(s.closes, 20)
macd, signal, hist = ta.macd(s.closes)
print(s.close, ema[-1], rsi[-1])
```

Also available: `ta.sma`, `ta.wma`, and `ta.stoch`, `ta.atr`, `ta.adx`,
which take `(high, low, close, ...)`. The first values of each array are
`NaN` until the window has enough bars.

!!! note
    This `ta` returns whole arrays. The `ta` in the authoring module returns
    only the latest value, or `None` while warming up.

## Trade

```python
r = buy(qty=1, price=1000.0)            # limit order, 1 share (odd lot)
print(r.status)
r = sell_order(qty=1, price=1500.0, symbol="2330")
```

Both return an `OrderResult` (`status`, `message`, `linked_order`), or
`None` if the call itself failed. `intraday_odd=True` is the default, so
`qty` is in shares.

!!! danger "Always give a price"
    `price=None` is sent as a limit price of `0`; it is not a market order.

!!! warning
    ArenaX answers a sell of shares the account does not hold with a
    `REJECTED` result; nothing is raised, so check `r.status`.

## Models

| Class | Fields you will use |
|---|---|
| `Order` | `id`, `product`, `action` (`OrderAction.BUY` / `SELL`), `price`, `quantity`, `price_type`, `order_type`, `order_lot` |
| `OrderType` | time in force: `ROD`, `IOC`, `FOK`, `GTC` |
| `Product` | `Product("2330")` |
| `Position` | `symbol`, `quantity`, `avg_cost`, `current_price`, `market_value`, `unrealized_pnl` |
| `Kbar` | `timestamp`, `open`, `high`, `low`, `close`, `volume`, `symbol` |

Full signatures are in the [API reference](../reference/beginner.md).
