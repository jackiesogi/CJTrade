# 連線到券商

CJTrade 的所有操作都透過同一個物件 `AccountClient`。建立它的時候選好券商，之後的
程式碼都不用改。

## ArenaX（模擬券商）

ArenaX 是 CJTrade 內建的模擬券商，不需要券商帳戶、也不會動到錢，就可以試用所有功能。

**1. 啟動它**：開一個終端機執行下面的指令，並讓它一直開著：

```sh
uv run arenaxd
```

**2. 從 Python 連線**：

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print(client.get_broker_name(), client.get_balance())

client.disconnect()
```

這樣就完成了。如果 `connect()` 失敗，等幾秒再試一次：ArenaX 要先載入價格資料，
才會接受連線。

!!! note
    ArenaX 用自己快速前進的時鐘重播真實價格，所以每次啟動時的價格都不一樣。

## 永豐金證券（Sinopac）

先安裝 `sinopac` extra，再傳入你的憑證：

```python
client = AccountClient(
    BrokerType.SINOPAC,
    api_key="...", secret_key="...",
    ca_path="/path/to/Sinopac.pfx", ca_passwd="...",
    simulation=True,      # 永豐的模擬環境
)
client.connect()
```

!!! danger "`simulation=False` 就是你的真實帳戶"
    你下的每一張單都是真的委託。請先在 ArenaX 上測試你的程式。

下一步：[帳戶與委託](account-and-orders.md)。
