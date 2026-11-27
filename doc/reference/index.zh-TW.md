# API 參考

API 頁面由 docstring 產生，每頁涵蓋一個模組的類別、函式及其參數。可用搜尋或下表
找到對應頁面。

| 你想要 | 頁面 |
|---|---|
| 連線、讀取帳戶、下委託 | [AccountClient](account-client.md) |
| 撰寫自己的券商轉接層 | [券商介面](broker-base.md) |
| 直接和 ArenaX 溝通，包括它的時鐘 | [ArenaX 用戶端](arenax-client.md) |
| 了解正式券商的轉接層做了什麼 | [永豐金轉接層](sinopac.md)、[富邦轉接層](fubon.md) |
| 撰寫策略檔 | [策略撰寫](strategy-authoring.md)、[載入策略檔](user-strategy.md) |
| 撰寫以類別為基礎的策略 | [BaseStrategy](base-strategy.md)、[內建策略](strategies.md)、[策略參數](strategy-parameters.md) |
| 從任何來源取得價格 | [行情資料](market-data.md) |
| 查詢委託、K 棒或持股的欄位 | [資料模型](models.md) |
| 在記憶體中回測 | [回測引擎](backtest-engine.md)、[交易成本模型](cost-model.md) |
| 在委託送出前先檢查 | [風控閘門](risk.md) |
| 技術指標、報告、新聞、基本面、LLM、圖表 | [分析](technical.md)章節 |
| 設定和檔案存放位置 | [設定與路徑](config.md) |
| 為腳本建立表單 | [表單](forms.md) |

頁面慣例：

- 標有 `class` 或 `func` 標籤的標題代表一個類別或函式。第一段為說明；
  **Parameters** 列出參數，**Returns** 為回傳值，**Raises** 為可能拋出的例外。
- 項目下方的 **Source code** 可展開其實作。
- 以 `_` 開頭的名稱屬於內部使用，不會列出。

[入門](../get-started/install.md)頁面以實際範例說明相同的物件。
