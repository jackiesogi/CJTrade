# 帳戶與委託

這一頁要在 ArenaX 上買一股，看著委託成交、出現在持股裡，接著再下一筆不會成交的委託，然後把它取消。

請讓[連線到券商](connect.md)裡啟動的 ArenaX 繼續執行。這裡的每個範例都是完整的程式：存檔後用 `uv run python file.py` 執行。

## 委託的流程

```
 place_order ──▶ COMMITTED_WAIT_MATCHING ──▶ FILLED       (the price was reached)
                        │
                        ├──────────────────▶ CANCELLED    (you cancelled it, or the day ended)
                        │
 (checks fail) ─────────┴──────────────────▶ REJECTED     (bad price, not enough cash, ...)
```

| 狀態 | 意思 |
|---|---|
| `COMMITTED_WAIT_MATCHING` | 券商已接受委託，正在等價格到 |
| `COMMITTED_WAIT_MARKET_OPEN` | 在交易時段以外接受的委託，會等到 09:00 |
| `FILLED` | 已成交：現金和持股都變了 |
| `CANCELLED` | 不會成交了 |
| `REJECTED` | 券商拒絕了，原因寫在 `result.message` |

!!! warning "問題會以狀態回報，不會拋出錯誤"
    委託被拒絕時，下單的方法不會拋出例外。請一定要檢查 `result.status`。

## 買一股 {#buy-one-share}

為了確保成交，這個範例用比目前價格高 2% 的價格出價：

```python
import time
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

snap = client.get_snapshots([Product("2330")])[0]
print("last price:", snap.close)

price = round(snap.close * 1.02, 1)
result = client.buy_stock("2330", 1, price)     # 股票代號、股數、限價
print("order:", result.status.value, result.linked_order)

time.sleep(3)                                    # 讓 ArenaX 撮合
for t in client.list_orders():
    print("listed:", t.symbol, t.action, t.quantity, t.price, t.status)
print("positions:", client.get_positions())
print("balance:", client.get_balance())

client.disconnect()
```

- `get_snapshots` 回傳最新的報價，`.close` 是最新成交價。
- `buy_stock(symbol, quantity, price)` 下一筆限價買進委託。它交易的是**零股**，所以 `1` 就是一股。
- `result.linked_order` 是這筆委託的 id，取消時會用到。
- `list_orders()` 列出這個帳戶的委託和它們目前的狀態。

預期輸出（價格會和你的不同）：

```text
last price: 2370.0
order: COMMITTED_WAIT_MATCHING 1eed911f91df431f8cdfee65fad7722c
listed: 2330 BUY 1 2417.4 FILLED
positions: [Position(symbol='2330', quantity=1, avg_cost=2417.4, current_price=2375.0, market_value=2375.0, unrealized_pnl=-42.4)]
balance: 97562.6
```

發生了什麼事：

1. 委託被接受了（`COMMITTED_WAIT_MATCHING`）。
2. 幾秒內，ArenaX 用下一分鐘的價格撮合，`list_orders()` 顯示 `FILLED`。
3. 你現在持有 1 股。`unrealized_pnl` 是用 `current_price` 賣出時會賺或賠的金額。
4. 餘額減少了股價加上最低手續費 NT$20：100,000 − 2,417.4 − 20 = 97,562.6。

!!! warning "ArenaX 用你的限價成交"
    ArenaX 是用委託的價格記錄成交，而不是用市價。上面的例子中，市價 2,370 的股票你付了 2,417.4。正式券商會給你比較好的市價。出價請貼近市價，模擬出來的成本才會接近真實。

## 下一筆會等待的委託，再把它取消

買進價格遠低於市價時不會成交，委託會一直掛著，直到你取消：

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

預期輸出：

```text
placed: COMMITTED_WAIT_MATCHING
cancel: CANCELLED - Order cancelled successfully.
```

取消一筆已經成交的委託，會回傳 `REJECTED`，原因寫在 `message`。

## 賣出

`sell_stock` 的用法和 `buy_stock` 一樣。要用市價賣掉上面買的那一股：

```python
result = client.sell_stock("2330", 1, round(snap.close * 0.98, 1))
```

你只能賣自己持有的股票，賣超過持股會被 `REJECTED`。

## 完整控制：自己建立 `Order`

簡便函式已經能滿足大部分需求。如果想自己決定每個欄位：

```python
from cjtrade.pkgs.models.order import Order, OrderAction, OrderLot, OrderType, PriceType
from cjtrade.pkgs.models.product import Product

order = Order(
    product=Product("2330"),
    action=OrderAction.BUY,
    price=1000.0,
    quantity=1,
    price_type=PriceType.LMT,           # 限價委託
    order_type=OrderType.ROD,           # 當日有效
    order_lot=OrderLot.IntraDayOdd,     # 數量以股為單位
)
result = client.place_order(order)
```

!!! warning "`quantity` 的單位取決於 `order_lot`"
    `OrderLot.IntraDayOdd` 以**股**計算，`OrderLot.Common` 以**張（1,000 股）**計算。在正式帳戶上，`quantity=1` 可能是一股，也可能是一千股。

## 快速參考

| 呼叫 | 回傳 |
|---|---|
| `client.get_balance()` | 新台幣現金（`float`） |
| `client.get_positions()` | `Position(symbol, quantity, avg_cost, current_price, market_value, unrealized_pnl)` 的清單 |
| `client.buy_stock(symbol, qty, price)` / `sell_stock(...)` | `OrderResult(status, message, linked_order, ...)` |
| `client.place_order(order)` | `OrderResult` |
| `client.cancel_order(order_id)` | `OrderResult` |
| `client.list_orders()` | `Trade(id, symbol, action, quantity, price, status, ...)` 的清單 |
| `client.sync_state()` | 從券商更新未成交委託的狀態 |

所有方法都列在 [AccountClient 參考](../reference/account-client.md)裡。

下一步：[行情資料](market-data.md)。
