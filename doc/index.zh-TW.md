# CJTrade

CJTrade 是一個用來打造台灣證券交易所（TWSE）交易系統的 Python 框架。你用
CJTrade 的 API 寫好策略之後，同一份策略可以直接接上任何支援的券商：

- **ArenaX**：內建的模擬券商，用於展示、模擬交易和回測。它以本機 HTTP 伺服器的
  形式執行（`uv run arenaxd`）。
- **永豐金證券（Sinopac）**：真實券商，透過它的 `shioaji` SDK 連線。

!!! danger "不構成投資建議"
    CJTrade 可以對真實的券商帳戶下單，它送出的每一筆委託都由你負責。請先用
    ArenaX 測試策略，再用永豐的 `SIMULATION=y` 測試，最後才接真實帳戶。

## 安裝

從原始碼安裝，同時也會拿到各個 app 和測試：

```sh
git clone https://github.com/jackiesogi/CJTrade
cd CJTrade
uv sync
```

當作套件安裝。核心包含 ArenaX、回測、shell 和報表，其他整合都是 extra：

```sh
pip install 'cjtrade[sinopac,llm] @ git+https://github.com/jackiesogi/CJTrade'
```

| Extra | 加裝的套件 | 用途 |
|---|---|---|
| `sinopac` | `shioaji` | 永豐金券商，以及 ArenaX 的 `backtest` / `paper` backend |
| `llm` | `google-genai`、`openai` | LLM 用戶端（Gemini、Azure OpenAI） |
| `news` | `newsapi-python` | NewsAPI 新聞來源 |
| `all` | 以上全部 | |

## 接下來看哪裡

| 你想要 | 請看 |
|---|---|
| 啟動模擬券商並連線 | [連線到券商](get-started/connect.md) |
| 讀取帳戶、下單和取消委託 | [帳戶與委託](get-started/account-and-orders.md) |
| 取得報價、歷史 K 棒和技術指標 | [行情資料](get-started/market-data.md) |
| 寫一個策略檔並檢查它 | [撰寫策略](get-started/strategy.md) |
| 用歷史 K 棒跑策略 | [回測](get-started/backtesting.md) |
| 查某個 class 或函式 | [API 參考](reference/account-client.md) |

各個 app（互動式 shell、ArenaX 伺服器、trading engine、`insight`）的說明在
[GitHub 上的 README](https://github.com/jackiesogi/CJTrade#readme)。

!!! note
    API 還沒有穩定，1.0 之前名稱可能會改。API 參考裡的 docstring 只有英文版。
