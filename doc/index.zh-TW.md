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
| 連上券商、讀取帳戶、下單和取消委託 | [快速開始](guides/quickstart.md) |
| 寫一個策略檔並檢查它 | [撰寫策略](guides/strategy-authoring.md) |
| 在 Python 裡用歷史 K 棒跑策略 | [回測](guides/backtesting.md) |
| 在 REPL 裡用簡短的函式操作券商 | [Beginner API](guides/beginner-api.md) |
| 查某個 class 或函式 | [API 參考](reference/account-client.md) |

各個 app（互動式 shell、ArenaX 伺服器、trading engine、`insight`）的說明在
[GitHub 上的 README](https://github.com/jackiesogi/CJTrade#readme)。

!!! note
    API 還沒有穩定，1.0 之前名稱可能會改。「設計筆記」底下的頁面是過去的分析紀錄，
    不會隨程式更新。API 參考裡的 docstring 只有英文版。
