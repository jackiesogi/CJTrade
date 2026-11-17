# 帳戶與委託

以下範例假設已經有一個連線好的 `client`（見[連線到券商](connect.md)）。

## 讀取帳戶

```python
print(client.get_balance())             # 現金，單位新台幣

for p in client.get_positions():
    print(p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl)

for t in client.list_orders():          # 這次連線期間下的委託
    print(t.id, t.symbol, t.action, t.quantity, t.price, t.status)
```

## 下單

簡便寫法只要給股票代號、數量和限價：

```python
result = client.buy_stock("2330", 1, 1000.0)    # 1 股，價格 1000
print(result.status, result.linked_order)        # linked_order 是委託編號
```

`sell_stock` 的用法相同。預設是零股委託（`intraday_odd=True`），所以數量單位是股。

需要完整控制時，自己建立 `Order`：

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
    order_type=OrderType.ROD,           # 當日有效
    order_lot=OrderLot.IntraDayOdd,     # 數量單位是股
)
result = client.place_order(order)
```

!!! warning "數量單位由 `order_lot` 決定"
    `OrderLot.IntraDayOdd` 以**股**計算；`OrderLot.Common` 以**張（1,000 股）**計算。
    在真實券商上，同樣的 `quantity=1` 可能是 1 股，也可能是 1,000 股。

## 取消委託

```python
print(client.cancel_order(order.id).status)     # CANCELLED
```

已經成交的委託無法取消，會回傳 `REJECTED`，原因寫在 `result.message`。

!!! warning
    委託相關的呼叫出問題時，會在結果裡回報（`status` 是 `REJECTED`），不會丟出
    例外。請一律檢查 `result.status`。

下一步：[行情資料](market-data.md)。
