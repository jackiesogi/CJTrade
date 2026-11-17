# Account and orders

The examples assume a connected `client` (see
[Connect to a broker](connect.md)).

## Read the account

```python
print(client.get_balance())             # cash, in TWD

for p in client.get_positions():
    print(p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl)

for t in client.list_orders():          # orders placed this session
    print(t.id, t.symbol, t.action, t.quantity, t.price, t.status)
```

## Place an order

The shortcut takes a symbol, a quantity and a limit price:

```python
result = client.buy_stock("2330", 1, 1000.0)    # 1 share at 1000
print(result.status, result.linked_order)        # linked_order is the order id
```

`sell_stock` works the same way. By default these are odd-lot orders
(`intraday_odd=True`), so the quantity is in shares.

For full control, build an `Order`:

```python
from cjtrade.pkgs.models.order import (
    Order, OrderAction, OrderLot, OrderType, PriceType)
from cjtrade.pkgs.models.product import Product

order = Order(
    product=Product("2330"),
    action=OrderAction.BUY,
    price=1000.0,
    quantity=1,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD,           # good for the day
    order_lot=OrderLot.IntraDayOdd,     # quantity in shares
)
result = client.place_order(order)
```

!!! warning "Quantity units depend on `order_lot`"
    `OrderLot.IntraDayOdd` counts **shares**; `OrderLot.Common` counts
    **lots of 1,000 shares**. On a real broker the same `quantity=1` is one
    share or a thousand.

## Cancel an order

```python
print(client.cancel_order(order.id).status)     # CANCELLED
```

An order that already filled cannot be cancelled; the result is `REJECTED`
with the reason in `result.message`.

!!! warning
    Order calls report problems in the result (`status` is `REJECTED`), not
    as exceptions. Always check `result.status`.

Next: [Market data](market-data.md).
