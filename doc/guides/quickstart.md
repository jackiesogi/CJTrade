# Quickstart

This page connects to ArenaX, reads the account, places an order, cancels it,
and fetches historical bars. Everything on it runs against the simulated
broker, so nothing here costs money.

## 1. Start ArenaX

```sh
uv run arenaxd --backend=demo
```

It listens on `127.0.0.1:8801`. Before it accepts a session it preloads price
data, which takes a few seconds; `curl -s http://127.0.0.1:8801/health`
reports `"running": true` when it is ready.

!!! warning "The demo clock starts at a random point"
    The `demo` backend picks its starting market time at random inside the
    preloaded window, and the clock keeps moving (120x by default). Prices,
    and whether an order fills, are therefore different on every launch. Use
    the [trading engine](https://github.com/jackiesogi/CJTrade#trading-engine)
    or [Backtesting](backtesting.md) when you need repeatable results.

## 2. Connect and read the account

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print(client.get_balance())        # cash, in TWD
print(client.get_positions())      # list of Position

snap = client.get_snapshots([Product("2330")])[0]
print(snap.symbol, snap.close)     # the day's quote so far
```

`testkey123` is the key ArenaX accepts. A Snapshot is a quote: its
`open`/`high`/`low` are the trading day's so far, not one bar's.

## 3. Place and cancel an order

```python
from cjtrade.pkgs.models.order import (
    Order, OrderAction, OrderLot, OrderType, PriceType)

order = Order(
    product=Product("2330"),
    action=OrderAction.BUY,
    price=round(snap.close * 0.9, 1),   # well below the market, so it rests
    quantity=1,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD,
    order_lot=OrderLot.IntraDayOdd,     # quantity in shares (odd lot)
)
result = client.place_order(order)
print(result.status)                    # COMMITTED_WAIT_MATCHING

print(client.cancel_order(order.id).status)   # CANCELLED
```

!!! warning "Quantity units depend on `order_lot`"
    With `OrderLot.IntraDayOdd` the quantity is in **shares**. With
    `OrderLot.Common` it is in **lots of 1,000 shares**. Against Sinopac the
    same `quantity=1` is either one share or a thousand.

!!! danger "The same code trades real money on Sinopac"
    Replace `BrokerType.ARENAX` with `BrokerType.SINOPAC` and every call
    above goes to Sinopac. `SinopacBrokerAPI` defaults to Sinopac's sandbox
    (`simulation=True`); pass `simulation=False` and it is your real account.
    The shell and the other apps pass `simulation=False` unless the
    `SIMULATION=y` setting is present. Sinopac needs `api_key`,
    `secret_key`, `ca_path` and `ca_passwd`.

## 4. Fetch historical bars

```python
kbars = client.get_kbars(Product("2330"), start="2025-01-01",
                         end="2025-10-01", interval="1d")
print(len(kbars), kbars[-1])

client.disconnect()
```

Supported intervals are `1m`, `5m`, `1h` and `1d`. ArenaX answers from its
local price cache and fetches what is missing from the network.

!!! warning
    An interval ArenaX does not know falls back to `1m` with only a printed
    message, and `get_kbars` returns `[]` rather than raising when nothing is
    available.
