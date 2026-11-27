# 設定與路徑

CJTrade 從哪裡讀取設定、有哪些設定，以及檔案寫到哪裡。

## 設定從哪裡來

一項設定就是一組 `KEY = value`。CJTrade 會依下列順序尋找每個鍵，並使用**第一個**
找到的值：

1. 環境變數（`export API_KEY=...`，或 `API_KEY=... command`），
2. 執行時所在資料夾中的 `.env` 檔，
3. 該資料夾或其子資料夾中的任何 `*.cjconf` 檔（層級較淺的資料夾優先，
   同層再依字母順序），
4. 使用者設定資料夾中的 `*.cjconf` 檔（見[路徑](#paths)），
5. CJTrade 內附的預設值（`*.cjsys` 檔）。

所以用 `export` 設定的值一定優先於檔案，專案裡的檔案也優先於使用者資料夾裡的檔案。

`*.cjconf` 檔存放你自己的設定和機密資料，不要放進 git（repository 的 `.gitignore`
已經排除了）。可以用 `bash scripts/gen_config.sh arenax` 或 `... sinopac` 建立一份
初始設定檔。

!!! tip "某個值是從哪個檔案來的？"
    `cjtrade.pkgs.config.config_loader.describe_sources()` 會印出每項設定，以及它
    來自哪個檔案或變數。

## 券商設定（`*.cjconf`）

| 鍵 | 適用對象 | 說明 |
|---|---|---|
| `API_KEY` | ArenaX、Sinopac | ArenaX：`testkey123`。Sinopac：你的 API key |
| `SECRET_KEY` | Sinopac | 你的 API secret |
| `CA_CERT_PATH` | Sinopac | `Sinopac.pfx` 憑證的路徑 |
| `CA_PASSWORD` | Sinopac | 憑證的密碼 |
| `SIMULATION` | Sinopac | `y` 為永豐的沙盒（模擬環境），`n` 為你的**正式帳戶**（產生出來的檔案是 `n`） |
| `LLM_MODEL`、`LLM_API_KEY`、`GEMINI_API_KEY` | LLM 用戶端、CJShell `llm` | 使用的模型及其金鑰 |
| `FINMIND_TOKEN` | FinMind 價格來源 | 選填；可提高請求次數上限 |

## CJTrade 全域變數

| 變數 | 說明 |
|---|---|
| `CJTRADE_HOME` | 把下方所有資料夾都放在這個路徑底下 |
| `CJTRADE_OFFLINE=1` | 所有網路價格來源都直接失敗，不會連線 |
| `CJTRADE_LOG_LEVEL` | `DEBUG`、`INFO`（預設）、`WARNING`、... |
| `ARENAX_PORT` | `AccountClient` 連到 ArenaX 的埠（預設 8801） |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | 啟動 `arenaxd --backend=real` 時必須設定 |

## ArenaX 伺服器設定（`AX_*`） {#arenax-server-settings}

每個 backend 的預設值在 `src/cjtrade/apps/ArenaX/configs/<backend>.cjsys`；
設定對應的變數即可覆寫。

| 變數 | 預設值（demo） | 說明 |
|---|---|---|
| `AX_HOST_PORT` | 8801 | 埠（backtest 8802、paper 8803、real 8888） |
| `AX_DATA_SOURCES` | `yfinance` | 價格來源，同 `--data` |
| `AX_PRICE_DB_PATH` | 共用快取 | 價格檔，同 `--price-db` |
| `AX_INITIAL_BALANCE` | 100000 | 新帳戶的起始現金 |
| `AX_STATE_FILE` | | 要接續的帳戶快照，不從全新帳戶開始 |
| `AX_BACKTEST_DURATION_DAYS` | 11（backtest 300） | 從開始日期起要載入幾天的價格 |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 | 每實際一秒前進的市場秒數 |
| `AX_SKIP_NON_TRADING_HOURS` | `y` | 跳過夜間和週末 |
| `AX_COMMISSION_DISCOUNT` | 1.0 | 0.6 代表手續費打六折 |
| `AX_SLIPPAGE_MODEL`、`AX_SLIPPAGE_PCT` | `none`、0.0005 | 滑價模型和幅度（尚未套用到 ArenaX 的成交） |

## FinHub 設定（`FINHUB_*`）

見 [FinHub README](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/apps/FinHub/README.md#settings)。

## 路徑 {#paths}

| 資料夾 | 存放內容 | macOS | Linux |
|---|---|---|---|
| config | `*.cjconf`、`finhub.env` | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| data | 報告、帳戶快照、FinHub 的資料庫 | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| cache | 價格快取 `arenax_price.db` | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |
| state、logs | 執行期狀態、日誌檔 | `~/Library/Application Support/cjtrade`、`~/Library/Logs/cjtrade` | `~/.local/state/cjtrade`、`~/.local/state/cjtrade/log` |

設定 `CJTRADE_HOME=/some/path` 後，這些資料夾會變成 `/some/path/config`、
`/some/path/data`、`/some/path/cache`、`/some/path/state` 和
`/some/path/logs`。`arenaxd` 啟動時會印出它使用的資料夾。

## API

!!! warning
    `load_supported_config_files()` 會寫入整個 process 的 `os.environ`（先找到的
    來源優先），`paths` 的輔助函式第一次被呼叫時會建立目錄。

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
