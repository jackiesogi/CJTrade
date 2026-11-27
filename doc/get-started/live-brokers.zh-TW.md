# 實盤券商

以 `AccountClient` 撰寫的程式不綁定任何券商。券商只是一個參數 `BrokerType`；在它背後，由轉接層（adapter）負責在 CJTrade 的資料模型和券商 SDK 之間轉換。把策略從 ArenaX 搬到正式帳戶，或從一家券商換到另一家，只要改這個參數和登入資訊，其他程式碼都不用動。

!!! warning "Fubon 與 Yuanta：測試中（testing in progress），使用風險請自行承擔"
    Fubon 和 Yuanta 的轉接層依照各券商官方的 SDK 與文件撰寫，並通過單元測試，但**尚未在正式帳戶上實際下過單**。委託狀態、數量單位和回報內容可能與文件描述不同。請先用離市價很遠的零股委託試驗，並逐筆對照券商自己的 App；確認無誤之前不要放大部位。目前只有 Sinopac 經過真實委託的測試。

```mermaid
flowchart LR
    Code["策略、交易引擎、<br/>CJShell、你的程式"] --> AC["AccountClient"]
    AC --> AX["ArenaXBrokerAPI_v2"] -- "HTTP" --> AXS["ArenaX<br/>（模擬）"]
    AC --> SP["SinopacBrokerAPI"] -- "shioaji" --> SPS["永豐金證券 Sinopac"]
    AC --> FB["FubonBrokerAPI"] -- "fubon_neo" --> FBS["富邦證券 Fubon"]
    AC --> YT["YuantaBrokerAPI"] -- "Spark API（.NET）" --> YTS["元大證券 Yuanta"]
    AC -. "client.market" .-> MD["MarketData<br/>FinMind · Yahoo · Sinopac · 價格檔"]
```

## 轉接層負責的轉換

每個轉接層轉換的項目相同，因此 CJTrade 的其他部分只需要面對一套模型：

| CJTrade | Sinopac（`shioaji`） | Fubon（`fubon_neo`） | Yuanta（Spark API） |
|---|---|---|---|
| `Order.action` BUY / SELL | `Action.Buy` / `Sell` | `BSAction.Buy` / `Sell` | `BuySell` `"B"` / `"S"` |
| `Order.order_lot` Common / IntraDayOdd | `StockOrderLot.Common` / `IntradayOdd` | `MarketType.Common` / `IntradayOdd` | `APCode` 0 / 4 |
| `Order.quantity`（整股以張、零股以股計） | 單位相同 | 一律以股計：整股 × 1,000 | 單位相同（`OrderQty`） |
| `Order.price`（float） | float | 字串（`"66.5"`） | float，市價單為 0 |
| `Order.price_type` LMT / MKT | `StockPriceType.LMT` / `MKT` | `PriceType.Limit` / `Market` | `PriceFlag` `" "` / `"M"` |
| `Order.order_type` ROD / IOC / FOK | `OrderType.ROD` / `IOC` / `FOK` | `TimeInForce.ROD` / `IOC` / `FOK` | `Time_in_force` `"0"` / `"3"` / `"4"` |
| `OrderStatus` | 由 `Status`（PendingSubmit、Submitted、Filled 等）轉換 | 由數字 `status`（0、10、30、40、50、90 等）與已成交數量判斷 | 由 `OrderStatus`（0、5、10、20、24、25、30）與 `OkQty` / `AfterQty` 判斷 |
| CJTrade 委託 id ↔ 券商 id | shioaji 的 order id，存於鏡像資料庫 | `<date>:<seq_no>`，存於鏡像資料庫，並附上 `user_def` 標記 | `<date>:<OrderNo>`，存於鏡像資料庫；完整的 CJTrade id 放在 `BasketNo` 隨委託送出 |
| 成交回報 → `OrderEvent` | 委託與成交 callback | `set_on_order`、`set_on_order_changed`、`set_on_filled` | `RR_RealReport`（委託回報 50、成交回報 51） |

鏡像資料庫（`paths.mirror_db_path("<broker>")`）記錄每一筆經由 CJTrade 送出的委託，以及它對應的券商 id，因此程式重啟後仍能找到、列出並取消這些委託。

## 功能比較

| | ArenaX | Sinopac | Fubon | Yuanta |
|---|---|---|---|---|
| 選用套件 | 不需要 | `sinopac` | `fubon` | `yuanta`，另需 .NET 8 與元大的 Spark API 檔案 |
| 委託：下單、取消、列出、`sync_state` | ✓ | ✓ | ✓ | ✓ |
| 餘額與持股 | ✓ | ✓ | ✓ | ✓ |
| 報價（`get_snapshots`、`get_bid_ask`） | ✓ | ✓，五檔 | ✓，僅最佳一檔 | ✓，僅最佳一檔 |
| 歷史 K 棒（`client.market`） | ✓ | ✓ | –，請傳入 `market=`（FinMind、Yahoo 等） | –，請傳入 `market=` |
| 成交與狀態 callback | –，請輪詢 `sync_state()` | ✓ | ✓ | ✓ |
| 沙盒（模擬環境） | 本身就是模擬 | `simulation=True` | 無：每筆委託都是真的 | `environment="UAT"`，預設值（需開通 API 權限並登記固定 IP） |
| 部分成交回報為 `PARTIAL` | –，一律全部成交 | ✓ | ✓ | ✓ |
| 已用真實委託測試 | 不適用 | ✓ | 尚未：測試中 | 尚未：測試中 |

## Sinopac

需要安裝 `sinopac` 選用套件，並從 [Sinopac 的 API 網站](https://ai.sinotrade.com.tw/python/Main/index.aspx#pag4)取得 API 金鑰、密鑰和憑證：

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(
    BrokerType.SINOPAC,
    api_key="...", secret_key="...",
    ca_path="/path/to/Sinopac.pfx", ca_passwd="...",
    simulation=True,      # Sinopac 的沙盒：委託不是真的
)
client.connect()
```

從設定讀取相同的參數：`AccountClient(BrokerType.SINOPAC, **sinopac_config())`，對應的設定為 `SINOPAC_API_KEY`、`SINOPAC_SECRET_KEY`、`SINOPAC_CA_CERT_PATH`、`SINOPAC_CA_PASSWORD` 和 `SINOPAC_SIMULATION`。

!!! danger "`simulation=False` 就是你的正式帳戶"
    設成 `simulation=False` 時，每一筆委託都是動用真實資金的真實委託。在程式於 ArenaX 和沙盒上都正確執行之前，請保持 `simulation=True`。

## Fubon

需要安裝 `fubon` 選用套件（`pip install 'cjtrade[fubon]'`，會安裝 [`fubon-neo`](https://pypi.org/project/fubon-neo/)）、已簽署 API 使用同意書的富邦證券帳戶，以及該帳戶的憑證。開戶與申請流程請見[富邦新一代 API 文件](https://www.fbs.com.tw/TradeAPI/docs/welcome/)。

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

client = AccountClient(
    BrokerType.FUBON,
    personal_id="A123456789",           # 身分證字號
    api_key="...",                      # 或以 password="..." 用密碼登入
    cert_path="/path/to/A123456789.pfx",
    cert_pass="...",                    # SDK 預設為 personal_id
    market=Cached(Fallback([FinMindMarketData(), YFinanceMarketData()])),
)
client.connect()
print(client.get_balance())
```

| 參數 | 意義 |
|---|---|
| `personal_id` | 帳戶持有人的身分證字號 |
| `api_key` 或 `password` | API 金鑰登入（`apikey_login`）或密碼登入（`login`） |
| `cert_path`、`cert_pass` | `.pfx` 憑證及其密碼 |
| `account` | 登入回傳多個帳號時要交易的帳號；預設為第一個證券帳號 |
| `market` | K 棒的來源；Fubon 轉接層只提供報價，不提供 K 棒 |

改從設定讀取（`FUBON_PERSONAL_ID`、`FUBON_API_KEY` 或 `FUBON_PASSWORD`、`FUBON_CERT_PATH`、`FUBON_CERT_PASSWORD`、`FUBON_ACCOUNT`；見[設定與路徑](../reference/config.md)）：

```python
from cjtrade.pkgs.config.broker_settings import fubon_config
from cjtrade.pkgs.config.config_loader import load_supported_config_files

load_supported_config_files()
client = AccountClient(BrokerType.FUBON, **fubon_config(), market=...)
```

Fubon 特有的行為：

- 委託送出前會先依富邦的規則檢查：零股限 1 到 999 股且只能 ROD，整股限 1 到 499 張，市價單只限整股。不符合規則的委託直接回傳 `REJECTED`，不會送到券商。
- `get_bid_ask` 只回傳最佳一檔買賣價。
- `list_orders()` 回傳帳戶當日的所有委託，包含不是經由 CJTrade 送出的委託，這些委託的 `id` 為 `'N/A'`。

!!! danger "Fubon 沒有沙盒；測試中"
    `fubon_neo` 沒有模擬環境的開關，因此經由 `BrokerType.FUBON` 送出的每一筆委託都是真實委託。這個轉接層已用 SDK 本身的委託與列舉型別做過單元測試，但尚未在正式帳戶上執行過：使用風險請自行承擔，並先用離市價很遠的零股委託試驗。

## Yuanta

元大的 Spark API 是由元大自行發佈的 .NET 8 元件（`YuantaSparkAPI.dll`），不在 PyPI 上。需要準備：

1. API 權限，請所屬營業員開通；測試環境（UAT）另需登記固定 IP；
2. 元大的 Spark API 檔案（範例程式中含 `.dll`、`.so`、`.dylib` 的資料夾），見[元大 Spark API 說明文件](https://www.yuanta.com.tw/file-repository/content/sparkapi_docs/)；
3. .NET 8 執行環境，以及 `yuanta` 選用套件（`pip install 'cjtrade[yuanta]'`，會安裝 `pythonnet`）。

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

client = AccountClient(
    BrokerType.YUANTA,
    account="S98875005091",          # S + 分公司代號（4）+ 帳號（7）
    password="...",
    cert_path="/path/to/cert.pfx",   # Linux 與 macOS 必填
    cert_pass="...",
    dll_dir="/path/to/YuantaSparkAPI",
    environment="UAT",               # 元大的測試環境；"PROD" 為正式帳戶
    market=Cached(Fallback([FinMindMarketData(), YFinanceMarketData()])),
)
client.connect()
```

從設定讀取：`AccountClient(BrokerType.YUANTA, **yuanta_config())`，對應 `YUANTA_ACCOUNT`、`YUANTA_PASSWORD`、`YUANTA_CERT_PATH`、`YUANTA_CERT_PASSWORD`、`YUANTA_DLL_DIR` 和 `YUANTA_ENVIRONMENT`（可用 `bash scripts/gen_config.sh yuanta` 產生）。

Yuanta 特有的行為：

- Spark API 是非同步的：每個呼叫會立即返回，結果之後經由 `OnResponse` 事件送達。轉接層會等待該回應（`timeout`，預設 10 秒），因此它的方法和其他券商一樣是同步呼叫。
- 同一個功能的呼叫會拉開間隔，以符合元大帳務類每秒 3 次的限制。
- 報價先以上市（TWSE）查詢，查不到再以上櫃（TWOTC）查詢。
- 回報的數量以股計；整股委託顯示的數量以張計。
- 在 UAT 中，是否成交依元大的測試規則（由委託書號最後一碼決定），而不是依市場價格。

!!! danger "`environment=\"PROD\"` 就是你的正式帳戶；測試中"
    在轉接層於測試環境中正常運作之前，請保持 `environment="UAT"`。Yuanta 轉接層尚未在正式帳戶上下過單：使用風險請自行承擔。

## 新增券商

轉接層繼承 `BrokerAPIBase` 並實作其抽象方法，`AccountClient` 再多一個 `BrokerType` 分支即可。詳見[券商介面](../reference/broker-base.md)和 [brokers README](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/pkgs/brokers/README.md)。

下一步：[帳戶與委託](account-and-orders.md)。
