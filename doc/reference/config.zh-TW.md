# 設定與路徑

設定的來源與優先順序、可用的設定，以及 CJTrade 寫入檔案的目錄。

## 設定從哪裡來

設定為 `KEY = value` 形式。每個鍵依下列順序查找，採用**第一個**找到的值：

1. 環境變數（`export API_KEY=...`，或 `API_KEY=... command`），
2. 工作目錄中的 `.env` 檔，
3. 工作目錄或其子目錄中的任何 `*.cjconf` 檔（層級較淺的目錄優先，同層依字母
   順序），
4. 使用者設定目錄中的 `*.cjconf` 檔（見[路徑](#paths)），
5. CJTrade 內附的預設值（`*.cjsys` 檔）。

因此 `export` 的變數優先於任何檔案，專案中的檔案優先於使用者設定目錄中的檔案。

`*.cjconf` 檔存放個人設定和機密資料，不應納入 git（repository 的 `.gitignore`
已排除）。以 `bash scripts/gen_config.sh arenax` 或 `... sinopac` 產生初始設定檔。

!!! tip "某個值是從哪個檔案來的？"
    `cjtrade.pkgs.config.config_loader.describe_sources()` 會印出每項設定及其
    來源檔案或變數。

## 券商設定（`*.cjconf`）

| 鍵 | 適用對象 | 說明 |
|---|---|---|
| `API_KEY` | ArenaX | `testkey123`，每個 ArenaX 伺服器都接受的金鑰 |
| `SINOPAC_API_KEY` | Sinopac | 你的 API key |
| `SINOPAC_SECRET_KEY` | Sinopac | 你的 API secret |
| `SINOPAC_CA_CERT_PATH` | Sinopac | `Sinopac.pfx` 憑證的路徑 |
| `SINOPAC_CA_PASSWORD` | Sinopac | 憑證的密碼 |
| `SINOPAC_SIMULATION` | Sinopac | `y` 為永豐的沙盒（模擬環境），`n` 為你的**正式帳戶**（產生出來的檔案是 `n`） |
| `FUBON_PERSONAL_ID` | Fubon | 帳戶持有人的身分證字號 |
| `FUBON_API_KEY` 或 `FUBON_PASSWORD` | Fubon | API 金鑰登入，或密碼登入 |
| `FUBON_CERT_PATH`、`FUBON_CERT_PASSWORD` | Fubon | `.pfx` 憑證及其密碼 |
| `FUBON_ACCOUNT` | Fubon | 選填：登入回傳多個帳號時要交易的帳號 |
| `LLM_MODEL`、`LLM_API_KEY`、`GEMINI_API_KEY` | LLM 用戶端、CJShell `llm` | 使用的模型及其金鑰 |
| `FINMIND_TOKEN` | FinMind 價格來源 | 選填；可提高請求次數上限 |

`bash scripts/gen_config.sh sinopac` 和 `... fubon` 會寫出包含這些鍵的設定檔。`cjtrade.pkgs.config.broker_settings` 會把它們轉成 `AccountClient` 的參數，例如 `AccountClient(BrokerType.FUBON, **fubon_config())`。

!!! note "Sinopac 的舊名稱"
    Sinopac 的鍵以前沒有前綴（`API_KEY`、`SECRET_KEY`、`CA_CERT_PATH`、`CA_PASSWORD`、`SIMULATION`）。在 `SINOPAC_` 名稱未設定時仍會讀取舊名稱，並記錄一則警告。`SINOPAC_SIMULATION` 或 `SIMULATION` 任一個為 `y` 時，就會使用沙盒。

## CJTrade 全域變數

| 變數 | 說明 |
|---|---|
| `CJTRADE_HOME` | 下方「路徑」表中所有目錄的根目錄 |
| `CJTRADE_OFFLINE=1` | 網路價格來源直接失敗，不嘗試連線 |
| `CJTRADE_LOG_LEVEL` | `DEBUG`、`INFO`（預設）、`WARNING`、... |
| `ARENAX_PORT` | `AccountClient` 連到 ArenaX 的埠（預設 8801） |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | 啟動 `arenaxd --backend=real` 時必須設定 |

## ArenaX 伺服器設定（`AX_*`） {#arenax-server-settings}

各 backend 的預設值位於 `src/cjtrade/apps/ArenaX/configs/<backend>.cjsys`；
設定對應的變數即可覆寫。

| 變數 | 預設值（demo） | 說明 |
|---|---|---|
| `AX_HOST_PORT` | 8801 | 埠（backtest 8802、paper 8803、real 8888） |
| `AX_DATA_SOURCES` | `yfinance` | 價格來源，同 `--data` |
| `AX_PRICE_DB_PATH` | 共用快取 | 價格檔，同 `--price-db` |
| `AX_INITIAL_BALANCE` | 100000 | 新帳戶的起始現金 |
| `AX_STATE_FILE` | | 從此帳戶快照接續，而非建立全新帳戶 |
| `AX_BACKTEST_DURATION_DAYS` | 11（backtest 300） | 從開始日期起要載入幾天的價格 |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 | 每實際一秒前進的市場秒數 |
| `AX_SKIP_NON_TRADING_HOURS` | `y` | 跳過夜間和週末 |
| `AX_COMMISSION_DISCOUNT` | 1.0 | 手續費乘數；0.6 代表手續費打六折 |
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
`/some/path/logs`。`arenaxd` 啟動時會印出使用的目錄。

## API

!!! warning
    `load_supported_config_files()` 會寫入整個 process 的 `os.environ`（先找到的
    來源優先），`paths` 的輔助函式第一次被呼叫時會建立目錄。

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
