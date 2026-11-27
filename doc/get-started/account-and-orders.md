# Account and orders

In this page you buy one share on ArenaX, watch the order fill, see it in
your positions, and then place and cancel an order that does not fill.

Keep ArenaX running from [Connect to a broker](connect.md). Every example
here is a complete script: save it, then run it with `uv run python file.py`.

## How an order moves

```
 place_order ──▶ COMMITTED_WAIT_MATCHING ──▶ FILLED       (the price was reached)
                        │
                        ├──────────────────▶ CANCELLED    (you cancelled it, or the day ended)
                        │
 (checks fail) ─────────┴──────────────────▶ REJECTED     (bad price, not enough cash, ...)
```

| Status | Meaning |
|---|---|
| `COMMITTED_WAIT_MATCHING` | the broker accepted the order and is waiting for the price |
| `COMMITTED_WAIT_MARKET_OPEN` | accepted outside trading hours; it waits for 09:00 |
| `FILLED` | it happened: cash and shares changed |
| `CANCELLED` | it will not happen |
| `REJECTED` | the broker refused it; `result.message` says why |

!!! warning "Problems come back as a status, not an error"
    Order methods do not raise when an order is refused. Always check
    `result.status`.

## Buy one share {#buy-one-share}

To make sure the order fills, this example bids 2% above the current price:

```python
import time
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

snap = client.get_snapshots([Product("2330")])[0]
print("last price:", snap.close)

price = round(snap.close * 1.02, 1)
result = client.buy_stock("2330", 1, price)     # symbol, shares, limit price
print("order:", result.status.value, result.linked_order)

time.sleep(3)                                    # let ArenaX match it
for t in client.list_orders():
    print("listed:", t.symbol, t.action, t.quantity, t.price, t.status)
print("positions:", client.get_positions())
print("balance:", client.get_balance())

client.disconnect()
```

- `get_snapshots` returns the latest quote; `.close` is the last traded
  price.
- `buy_stock(symbol, quantity, price)` places a limit buy. It trades **odd
  lots**, so `1` is one share.
- `result.linked_order` is the order's id. You need it to cancel.
- `list_orders()` lists this account's orders with their current status.

Expected output (your prices will differ):

```text
last price: 2370.0
order: COMMITTED_WAIT_MATCHING 1eed911f91df431f8cdfee65fad7722c
listed: 2330 BUY 1 2417.4 FILLED
positions: [Position(symbol='2330', quantity=1, avg_cost=2417.4, current_price=2375.0, market_value=2375.0, unrealized_pnl=-42.4)]
balance: 97562.6
```

What happened:

1. The order was accepted (`COMMITTED_WAIT_MATCHING`).
2. Within a few seconds ArenaX matched it against the next minute's prices,
   and `list_orders()` shows `FILLED`.
3. You now hold 1 share. `unrealized_pnl` is what you would gain or lose by
   selling at `current_price`.
4. The balance dropped by the price plus the minimum NT$20 commission:
   100,000 − 2,417.4 − 20 = 97,562.6.

!!! warning "ArenaX fills at your limit price"
    ArenaX books a fill at the order's price, not at the market price. Above
    you paid 2,417.4 for a share trading at 2,370. A real broker would give
    you the better market price. Bid close to the market to keep simulated
    costs realistic.

## Place an order that waits, then cancel it

A buy far below the market will not fill, so it stays open until you cancel
it:

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

snap = client.get_snapshots([Product("2330")])[0]
result = client.buy_stock("2330", 1, round(snap.close * 0.8, 1))
print("placed:", result.status.value)

cancel = client.cancel_order(result.linked_order)
print("cancel:", cancel.status.value, "-", cancel.message)

client.disconnect()
```

Expected output:

```text
placed: COMMITTED_WAIT_MATCHING
cancel: CANCELLED - Order cancelled successfully.
```

Cancelling an order that already filled returns `REJECTED` with the reason
in `message`.

## Sell

`sell_stock` works like `buy_stock`. To sell the share bought above at the
market:

```python
result = client.sell_stock("2330", 1, round(snap.close * 0.98, 1))
```

You can only sell shares you hold; selling more is `REJECTED`.

## Full control: build an `Order`

The shortcuts cover most needs. To choose every field yourself:

```python
from cjtrade.pkgs.models.order import Order, OrderAction, OrderLot, OrderType, PriceType
from cjtrade.pkgs.models.product import Product

order = Order(
    product=Product("2330"),
    action=OrderAction.BUY,
    price=1000.0,
    quantity=1,
    price_type=PriceType.LMT,           # a limit order
    order_type=OrderType.ROD,           # good for the rest of the day
    order_lot=OrderLot.IntraDayOdd,     # quantity in shares
)
result = client.place_order(order)
```

!!! warning "What `quantity` counts depends on `order_lot`"
    `OrderLot.IntraDayOdd` counts **shares**. `OrderLot.Common` counts
    **lots of 1,000 shares**. On a real account, `quantity=1` is either one
    share or a thousand.

## Quick reference

| Call | Returns |
|---|---|
| `client.get_balance()` | cash in NT$ (`float`) |
| `client.get_positions()` | list of `Position(symbol, quantity, avg_cost, current_price, market_value, unrealized_pnl)` |
| `client.buy_stock(symbol, qty, price)` / `sell_stock(...)` | `OrderResult(status, message, linked_order, ...)` |
| `client.place_order(order)` | `OrderResult` |
| `client.cancel_order(order_id)` | `OrderResult` |
| `client.list_orders()` | list of `Trade(id, symbol, action, quantity, price, status, ...)` |
| `client.sync_state()` | refreshes the status of open orders from the broker |

Every method is listed in the [AccountClient reference](../reference/account-client.md).

Next: [Market data](market-data.md).
