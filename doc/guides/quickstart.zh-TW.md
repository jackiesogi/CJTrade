# 快速開始

這一頁會連上 ArenaX、讀取帳戶、下一張單、把它取消，再抓歷史 K 棒。全部都在模擬
券商上執行，不會花到錢。

## 1. 啟動 ArenaX

```sh
uv run arenaxd --backend=demo
```

它會監聽 `127.0.0.1:8801`。接受連線前會先預載價格資料，需要幾秒鐘；
`curl -s http://127.0.0.1:8801/health` 回傳 `"running": true` 時就代表準備好了。

!!! warning "demo 的時鐘起點是隨機的"
    `demo` backend 會在預載的時間範圍內隨機挑一個起始的市場時間，而且時鐘會一直
    往前走（預設 120 倍速）。所以每次啟動時，價格和委託會不會成交都不一樣。需要
    可重現的結果時，請用 [trading engine](https://github.com/jackiesogi/CJTrade#trading-engine)
    或[回測](backtesting.md)。

## 2. 連線並讀取帳戶

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print(client.get_balance())        # 現金，單位新台幣
print(client.get_positions())      # Position 的 list

snap = client.get_snapshots([Product("2330")])[0]
print(snap.symbol, snap.close)     # 當天到目前為止的報價
```

`testkey123` 是 ArenaX 接受的 key。Snapshot 是一筆報價，它的 `open`/`high`/`low`
是當天到目前為止的值，不是某一根 K 棒的。

## 3. 下單和取消

```python
from cjtrade.pkgs.models.order import (
    Order, OrderAction, OrderLot, OrderType, PriceType)

order = Order(
    product=Product("2330"),
    action=OrderAction.BUY,
    price=round(snap.close * 0.9, 1),   # 遠低於市價，所以會掛著不成交
    quantity=1,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD,
    order_lot=OrderLot.IntraDayOdd,     # 數量單位是股（零股）
)
result = client.place_order(order)
print(result.status)                    # COMMITTED_WAIT_MATCHING

print(client.cancel_order(order.id).status)   # CANCELLED
```

!!! warning "數量單位由 `order_lot` 決定"
    `OrderLot.IntraDayOdd` 的數量單位是**股**，`OrderLot.Common` 的數量單位是
    **張（1,000 股）**。在永豐上，同樣的 `quantity=1` 可能是 1 股，也可能是 1,000 股。

!!! danger "同樣的程式碼在永豐上會動到真錢"
    把 `BrokerType.ARENAX` 換成 `BrokerType.SINOPAC`，上面每個呼叫都會送到永豐。
    `SinopacBrokerAPI` 預設用永豐的模擬環境（`simulation=True`）；傳入
    `simulation=False` 就是你的真實帳戶。shell 和其他 app 在沒有 `SIMULATION=y`
    設定時，傳的都是 `simulation=False`。永豐需要 `api_key`、`secret_key`、
    `ca_path` 和 `ca_passwd`。

## 4. 抓歷史 K 棒

```python
kbars = client.get_kbars(Product("2330"), start="2025-01-01",
                         end="2025-10-01", interval="1d")
print(len(kbars), kbars[-1])

client.disconnect()
```

支援的 interval 有 `1m`、`5m`、`1h` 和 `1d`。ArenaX 會先從本機的價格快取回答，
缺少的部分再從網路抓。

!!! warning
    ArenaX 不認得的 interval 會退回 `1m`，只印一行訊息。沒有資料時 `get_kbars`
    回傳 `[]`，不會丟出例外。
