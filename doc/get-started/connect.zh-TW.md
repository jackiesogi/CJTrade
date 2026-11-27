# 連線到券商

這一頁要啟動模擬券商 ArenaX，再從 Python 連上它。做完之後，你會印出自己（模擬）帳戶的餘額。

你需要開兩個終端機視窗：一個執行 ArenaX，另一個執行你的程式。

## 步驟 1：啟動 ArenaX

在第一個終端機裡，進到 `CJTrade` 資料夾執行：

```sh
uv run arenaxd
```

這會用預設的 `demo` 模式啟動 ArenaX 伺服器。它會：

1. 挑一個 11 到 20 天前的交易日，
2. 從 Yahoo Finance 下載那段期間的 1 分鐘價格（不需要帳戶），並存進價格快取，
3. 開一個全新的模擬帳戶，裡面有 NT$100,000，
4. 在 `127.0.0.1:8801` 等待連線，只有你自己的電腦連得到。

幾秒後的預期輸出（有省略，日期會和你的不同）：

```text
[INFO][...] ArenaX.server: market data: yfinance
[INFO][...] ArenaX.backend.demo: market time: ... mock_current_time=2026-11-13 09:00:00 ... playback_speed=120.0 ...
[INFO][...] ArenaX.server: starting on 127.0.0.1:8801, backend=demo
[INFO][...] ArenaX.backend.state: fresh account
[INFO][...] ArenaX.backend: sim env started
```

`mock_current_time` 是 ArenaX 模擬出來的「現在」，`playback_speed=120.0` 表示真實的 1 秒等於市場的 2 分鐘。讓這個終端機保持執行。

??? question "出現 `[ERROR] yfinance: ... possibly delisted; no price data found`"
    ArenaX 要的某幾天在 Yahoo 上沒有 K 棒資料，通常是週末或假日。ArenaX 會用有拿到的日子繼續執行。只要最後有看到 `sim env started` 就沒問題。

## 步驟 2：從 Python 連線

在第二個終端機裡，把下面的程式存成 `hello.py`，再用 `uv run python hello.py` 執行：

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print("broker:", client.get_broker_name())
print("balance:", client.get_balance())
print("positions:", client.get_positions())
print("market time:", client.get_market_time()["mock_current_time"])

client.disconnect()
```

逐行說明：

- `AccountClient(BrokerType.ARENAX, ...)` 選擇券商。其餘的程式碼不管用哪家券商都一樣。`testkey123` 是每個 ArenaX 伺服器預設都接受的金鑰。
- `connect()` 開始連線。一定要搭配 `disconnect()` 使用。
- `get_balance()` 是你的現金，`get_positions()` 是你的持股。
- `get_market_time()` 詢問 ArenaX 它的模擬市場現在是幾點。

預期輸出：

```text
broker: arenax (8801)
balance: 100000.0
positions: []
market time: 2026-11-13 09:24:43.668600
```

新帳戶有 NT$100,000，沒有任何持股。過幾秒再執行一次，會發現市場時間往前走了：只要 ArenaX 還在執行，模擬時鐘就會一直走。

!!! note "帳戶跟著伺服器存在"
    斷線後再連線，餘額和持股都還在。重新啟動 `arenaxd` 則會在隨機挑選的新日期開一個全新的帳戶。

??? question "`connect()` 失敗，出現 `Connection refused`"
    ArenaX 沒有在執行，或還沒準備好。確認第一個終端機已經顯示 `sim env started`，再試一次。其他錯誤請看[疑難排解](troubleshooting.md)。

## Sinopac（正式券商）

準備好使用正式帳戶時，唯一要改的是建立 client 的方式。你需要安裝 `sinopac` 選用套件，並從 [Sinopac 的 API 網站](https://ai.sinotrade.com.tw/python/Main/index.aspx#pag4)取得 API 金鑰、密鑰和憑證：

```python
client = AccountClient(
    BrokerType.SINOPAC,
    api_key="...", secret_key="...",
    ca_path="/path/to/Sinopac.pfx", ca_passwd="...",
    simulation=True,      # Sinopac 的沙盒：委託不是真的
)
client.connect()
```

!!! danger "`simulation=False` 就是你的正式帳戶"
    設成 `simulation=False` 時，每一筆委託都是用真錢下的真委託。在你的程式於 ArenaX 和沙盒上都跑得正確之前，請保持 `simulation=True`。

不要把密鑰寫在程式碼裡，請放在設定檔中，詳見[設定與路徑](../reference/config.md)。

下一步：[帳戶與委託](account-and-orders.md)。
