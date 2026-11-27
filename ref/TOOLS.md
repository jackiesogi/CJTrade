# CJTrade 執行方式總覽

依據 commit `8fac4b7`（`feat/cjtrade-app`）的程式碼整理。所有指令都從 repo 根目錄執行。標示「（未驗證）」的項目是只讀程式碼推斷、沒有實際跑過的。

## 總表

| 指令 | 用途 | 需要券商帳號? | 預設 port |
|---|---|---|---|
| `uv run arenaxd` | ArenaX 模擬券商伺服器 | demo：否；backtest：預設要（可用 `--data` 避開）；paper/real：要 | 8801 demo / 8802 backtest / 8803 paper / 8888 real |
| `uv run aresh` | ArenaX 管理 shell | 否 | 連 `ARENAX_PORT` 或 8801（`--port` 可改） |
| `uv run cjshell -B arenax` / `-B sinopac` | 互動式交易 shell（CJShell） | arenax：否；sinopac：要 | 連 `ARENAX_PORT` 或 8801 |
| `uv run cjtrade` | CJTrade 交易引擎（多 bot），原 `poc/trading_engine` | 取決於 ArenaX 模式 | 連 ArenaX（依 mode）；狀態 API 8898；ZMQ 5555/5556 |
| `uv run finhub` | FinHub 網頁介面，會自己起 `arenaxd` 與 `cjtrade` | 取決於 run 的 mode 與 ArenaX 資料來源 | 8000；ArenaX 8802；引擎 8898 |
| `uv run backtest` | One-shot 向量化回測 | 取決於 ArenaX 伺服器 | 連 `ARENAX_PORT` 或 8801 |
| `uv run preload-prices` | 預先下載 K 線到價格快取 | 否（預設 finmind,yfinance） | — |
| `uv run insight` | 回測結果診斷報告 | 否 | — |
| `uv run strategy-tool` | 策略範本／檢查／API 清單（JSON） | 否 | — |
| `bash tests/test_cjtrade_integration_arenax.sh --broker=arenax --group=all` | CJShell 冒煙測試（ArenaX） | 否 | 必要時起 8801 |
| `bash tests/test_cjtrade_integration.sh --broker=sinopac --group=all` | CJShell 冒煙測試（永豐，**會下真單**） | 是 | — |
| `bash poc/backtest.sh` | 表單驅動的 one-shot 回測 | 取決於 mode | 起 8801/8802/8803；表單 9876 |
| `uv run python scripts/check_readme_examples.py` | 檢查 README 範例 | 否 | smoke 模式會啟動範例 |
| `uv run python scripts/price_db_report.py` | 價格快取完整度報告 | 否 | — |
| `uv run python src/cjtrade/apps/CJEdit/main.py` | 快速策略編輯器 | 範本依選擇而定 | — |
| `uv run python src/cjtrade/apps/CJNews/main.py` | 新聞搜尋 | 否（NewsAPI 要 key） | 表單 9876 |
| `uv run pytest` | 單元＋整合測試 | 否 | 整合測試需 8801 |
| `uv run --group docs mkdocs serve` | 本機文件站 | 否 | 8000（與 FinHub 預設相同） |

`[project.scripts]` 現在只有：`cjtrade`、`cjshell`、`arenaxd`、`aresh`、`backtest`、`strategy-tool`、`insight`、`preload-prices`、`finhub`。`main`、`test`、`atest`、`system`、`_system_direct` 已移除。

---

## 共用：路徑、設定檔與環境變數

### 資料存放位置（`src/cjtrade/pkgs/paths.py`）

以 platformdirs 決定位置。設定 `CJTRADE_HOME=/some/path` 後，所有類別改放到 `$CJTRADE_HOME/{data,config,cache,state,logs}`。

| 類別 | macOS 預設 | 內容 |
|---|---|---|
| data | `~/Library/Application Support/cjtrade` | `account_states/<uuid>.json`、`mirrors/<broker>_<user>.db`、`reports/`、`finhub/` |
| config | 同上（macOS 上與 data 相同） | 使用者層級 `*.cjconf`、`finhub.env` |
| cache | `~/Library/Caches/cjtrade` | `arenax_price.db`（ArenaX 價格快取，可刪） |
| state | 同 data | `form_state/<schema 檔名>.json`（表單記住的答案） |
| logs | `~/Library/Logs/cjtrade` | `shioaji.log`（永豐 SDK 的 log；cjtrade 本身的 log 只印到終端機） |
| reports | `<data>/reports` | `oneshot_*.pkl/.html`、`comparison_*.html`、`compare_*.html`、`fullreport_*.html`、`engine_*.pkl/.html/.equity.jsonl`、`*.insight.md/.json` |
| FinHub | `<data>/finhub` | `finhub.db`、`run_logs/run-<id>-<時間>.log`、`run_strategies/run-<id>/`（該 run 的策略檔與 `roster.json`） |

Linux 是 `~/.local/share/cjtrade`、`~/.cache/cjtrade` 等。`arenaxd` 啟動時會印出實際路徑（`paths.describe()`），若 `./data/` 還有舊檔也會提示搬移指令。

### `.cjconf`（券商／服務憑證，`pkgs/config/config_loader.py`）

規則是「先設定者勝」（`load_dotenv(override=False)`），順序：

1. 已存在的環境變數
2. `./.env`
3. `./**/*.cjconf`（目前目錄遞迴，淺層優先、同層依字母）
4. `<config dir>/*.cjconf`

常用 key：`API_KEY`、`SECRET_KEY`、`CA_CERT_PATH`、`CA_PASSWORD`、`SIMULATION`（`y` = 永豐模擬環境）、`USERNAME`、`LLM_API_KEY`、`LLM_MODEL`、`GEMINI_API_KEY`、`NEWSAPI_API_KEY`。只有永豐需要前四個；ArenaX 不需要任何 `.cjconf`。

產生範本（寫到目前目錄的 `<template>_system.cjconf`）：

```sh
bash scripts/gen_config.sh arenax     # API_KEY = testkey123，其他空白
bash scripts/gen_config.sh sinopac    # 需要自行填入永豐憑證
```

### 其他環境變數

| 變數 | 誰讀 | 作用 |
|---|---|---|
| `CJTRADE_HOME` | 全部 | 改變所有資料目錄 |
| `CJTRADE_LOG_LEVEL` | `setup_logging()` | 覆寫 log 等級 |
| `CJTRADE_OFFLINE=1` | `pkgs/marketdata` | 所有網路來源直接丟 `MarketDataUnavailable`，只用本機快取 |
| `FINMIND_TOKEN` | finmind 來源 | 選填；日線免 token，分線需贊助方案 |
| `SJ_LOG_PATH` | shioaji | 預設設成 `<logs>/shioaji.log`（`setdefault`，已設定就不動） |
| `AX_*` | `arenaxd` | 見 ArenaX 章節 |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | `arenaxd --backend=real` | 沒設就拒絕啟動 real 後端 |
| `ARENAX_HOST`（預設 localhost）、`ARENAX_PORT` | `cjshell`、`aresh`、`backtest`、`cjtrade`、`poc/experiments` 腳本 | 連哪個 ArenaX。`cjshell`／`aresh`／`backtest` 預設 8801；`cjtrade` 沒設時依 mode 用 8801／8802／8803 |
| `CJ_ENGINE_STATUS_PORT`（預設 8898） | `cjtrade` | 狀態 API port |
| `CJ_ENGINE_CONTROL_TOKEN` | `cjtrade` 狀態 API | 有設才開放 `POST /bots/{id}/stop`，且所有讀取也要帶 token；FinHub 起的 run 會自動產生 |
| `FINHUB_*` | `finhub` | 見 FinHub 章節 |
| `NEWS_SOURCE`（預設 cnyes）、`NEWSAPI_API_KEY` | `cjshell`、CJNews | 新聞來源 |
| `AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_DEPLOYMENT`、`AZURE_OPENAI_MODEL_NAME`、`CHATPDF_APIKEY`、`CHATPDF_BASIC_SOURCE_FILE`、`GEMINI_API_KEY` | `cjshell` 的 `llm` | LLM 用 |
| `CJ_CHECK_NO_SMOKE=1` | README 檢查器 | 只做靜態檢查 |

`CJSYS_*`（舊 `system` 啟動器）、`ALLOW_LEGACY_BROKER`、`NTFY_SH_*` 都隨 `apps/cjtrade_system` 一起刪除了。`poc/backtest.sh` 的表單仍輸出 `CJSYS_WATCH_LIST` 這個變數名，但只是腳本內部用。

---

## `arenaxd`：ArenaX 模擬券商伺服器

入口：`cjtrade.apps.ArenaX.brokerside_server:main`。本機 HTTP 伺服器，提供行情、撮合、帳戶。Swagger UI 在 `/docs`，OpenAPI 在 `/openapi.json`。

### 選項

| 選項 | 預設 | 說明 |
|---|---|---|
| `--backend {backtest,paper,demo,real}` | `demo` | 後端模式，決定載入哪個 `configs/<mode>.cjsys` |
| `--host HOST` | cjsys 的 `AX_HOST_ADDRESS`，再退回 `127.0.0.1` | 只接受 loopback（`localhost` 或 loopback IP），其他位址直接拒絕並結束 |
| `--port PORT` | cjsys 的 `AX_HOST_PORT`，再退回 8801 | |
| `--data SOURCES` | `AX_DATA_SOURCES`，再退回該模式預設 | 價格來源，依序嘗試：`sinopac`、`finmind`、`yfinance`、`cache`、`offline` |
| `--price-db FILE` | `AX_PRICE_DB_PATH`，再退回 `<cache>/arenax_price.db` | SQLite 價格快取 |

要從別台機器用，走 SSH：`ssh -L 8801:127.0.0.1:8801 <host>`。

### 模式

| 模式 | cjsys port | 預設 `--data` | 登入永豐? | 說明 |
|---|---|---|---|---|
| `demo` | 8801 | `yfinance` | 否 | 回測 11 天、120x，新手用 |
| `backtest` | 8802 | `sinopac,yfinance` | 是（因為 sinopac 在來源裡） | 回測 300 天、30000x；`--data=finmind,yfinance` 就不需登入 |
| `paper` | 8803 | `sinopac` | 是 | 即時行情模擬下單 |
| `real` | 8888 | `sinopac` | 是 | 真實下單；需 `I_UNDERSTAND_REAL_TRADING_RISKS=y` |

只有 `sinopac` 出現在來源裡，或模式是 paper/real 時才會登入永豐。

### `AX_*` 設定（`src/cjtrade/apps/ArenaX/configs/*.cjsys`）

先跑 `load_cjconf()`，再讀 `<mode>.cjsys`，同樣「先設定者勝」，所以環境變數會蓋過 cjsys。

| Key | demo / backtest / paper / real | 說明 |
|---|---|---|
| `AX_BACKTEST_DURATION_DAYS` | 11 / 300 / — / — | 回測天數（程式預設 365） |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 / 30000 / — / — | 播放倍速（程式預設 1.0） |
| `AX_INITIAL_BALANCE` | 註解掉（全新帳戶 100000） | 全新帳戶的起始現金。FinHub 會設成該 run 的 fund。有 `AX_STATE_FILE` 時只覆寫報表用的 `initial_balance`，不改現金 |
| `AX_HOST_ADDRESS` | 127.0.0.1 | 非 loopback 會被拒絕 |
| `AX_HOST_PORT` | 8801 / 8802 / 8803 / 8888 | |
| `AX_STATE_FILE` | 預設註解掉 | 要「接續」的帳戶快照；不設就是全新帳戶。每次執行都另存 `<data>/account_states/<uuid>.json` |
| `AX_SKIP_NON_TRADING_HOURS` | y / y / n / n | 自動跳過盤後與週末 |
| `AX_SKIP_DATA_PRELOAD` | n | 以 bool 解析（`y`/`yes`/`true`/`1` 為真） |
| `AX_COMMISSION_DISCOUNT` | 註解（1.0） | 手續費折扣，最低 NT$20 |
| `AX_SLIPPAGE_MODEL` | 註解（none） | `none`、`fixed_pct`、`fixed_tick` |
| `AX_SLIPPAGE_PCT` | 註解（0.0005） | 只用於 `fixed_pct` |
| `AX_DATA_SOURCES` | 未列在檔案中 | 同 `--data` |
| `AX_PRICE_DB_PATH` | 未列在檔案中 | 同 `--price-db` |

`AX_LAUNCH_MODE`、`AX_REAL_ACCOUNT_BROKER_TYPE`、`AX_AUTO_TIME_PROGRESS`、`AX_AUTO_START_BACKEND` 已從 cjsys 檔移除。

證交稅寫死：股票 0.3%、ETF（代號 0 開頭）0.1%，只在賣出時收。

`configs/parse_cjsys_config.sh <file>` 是開發輔助，把檔案裡的 `AX_` key 印成 Python list。

### HTTP 路由（`brokerside_server.py`）

時間一律是 naive Asia/Taipei ISO 8601。backend 還沒啟動時，除了 `/health`、`/api/v1/backend`、`/docs`、`/openapi.json` 之外都回 503。

| 群組 | 路由 | 說明 |
|---|---|---|
| Health | `GET /health` | `running`、`backend_connected`、`data_readiness`；不搶 backend lock |
| | `GET /api/v1/config` | 解析後的設定（密鑰已遮蔽） |
| Backend | `PUT /api/v1/backend` | `{"running": true\|false}` 啟停 backend |
| Clock | `GET /api/v1/clock` | 模擬時鐘（real/mock 起始與目前時間、倍速、是否暫停） |
| | `PATCH /api/v1/clock` | `{"mock_current_time": ISO}` 跳到某時刻（並凍結）、`{"paused": bool}` 暫停／繼續 |
| | `PUT /api/v1/clock/origin` | `{"mock_init_time", "auto_start_progress", "auto_preload_data"}` 設時間軸起點（對齊 09:00） |
| | `GET /api/v1/clock/timeline` | 參數 `symbols,start,end,interval`；回放要走的時間戳 |
| Session | `POST /api/v1/session` | `{"api_key": "..."}`；接受寫死的 `testkey123`，但沒有路由會檢查 session |
| | `DELETE /api/v1/session` | 登出 |
| Account | `GET /api/v1/account` | 餘額、部位、委託 |
| | `GET /api/v1/account/fills` | 參數 `session_id`、`limit`；建 BacktestResult 用 |
| Orders | `GET /api/v1/orders` | 參數 `open_only=true` 只列未完成 |
| | `POST /api/v1/orders` | 下單 |
| | `GET /api/v1/orders/<order_id>` | 單筆狀態 |
| | `DELETE /api/v1/orders/<order_id>` | 取消 |
| Market | `GET /api/v1/market/<symbol>/snapshot` | 最新快照 |
| | `GET /api/v1/market/<symbol>/kbars` | 參數 `start,end,interval`（`1m`、`5m`、`1h`、`1d`）；只回已收盤的 K 棒 |
| | `GET /api/v1/market/data-availability` | 已知券商資料起訖（資訊用） |

### 離線使用

```sh
uv run preload-prices --price-db exp.db --symbols 2330,2317 --start 2025-09-01 --end 2025-10-01
CJTRADE_OFFLINE=1 uv run arenaxd --backend=backtest --data=offline --price-db=exp.db
```

`--data=offline` 只回快取已有的資料；`CJTRADE_OFFLINE=1` 額外保證任何網路來源都不會被呼叫。

### 典型指令

```sh
uv run arenaxd                                         # demo，8801，yfinance
uv run arenaxd --backend=backtest --data=finmind,yfinance   # 8802，不需永豐
AX_INITIAL_BALANCE=1000000 uv run arenaxd --backend=backtest --data=finmind,yfinance
I_UNDERSTAND_REAL_TRADING_RISKS=y uv run arenaxd --backend=real
```

---

## `aresh`：ArenaX 管理 shell

入口：`cjtrade.apps.ArenaX.brokerside_server_admin_shell:main`。

| 選項 | 預設 | 說明 |
|---|---|---|
| `--host` | `ARENAX_HOST`，再退回 `localhost` | |
| `--port` | `ARENAX_PORT`，再退回 8801 | |

其餘參數當成一個指令執行後離開；沒有就進互動模式。

| 指令 | 說明 |
|---|---|
| `health` | 伺服器健康狀態 |
| `config` | 伺服器設定 |
| `start` / `stop` | 啟動／停止 backend |
| `set-time <YYYY-MM-DD>` | 設定模擬起始時間 |
| `pause` / `resume` | 暫停／恢復模擬時間 |
| `time` | 顯示系統時間 |
| `query <symbol>` | 查價 |
| `clear`、`help`、`exit` | |

```sh
uv run aresh
uv run aresh health
uv run aresh --port 8802 set-time 2025-09-01
```

---

## `cjshell`：互動式交易 shell（CJShell）

入口：`cjtrade.apps.CJShell.cjshell:main`（`src/cjtrade/apps/CJShell/cjshell.py`）。同目錄的 `cjshell_legacy.py` 是只支援 sinopac 的舊版，沒有 console script，只給 `tests/test_cjtrade_integration.sh` 與單元測試用。

### 啟動

- 必要選項 `-B/--broker`。
- 會載入 `.cjconf`，但只有 `--broker=sinopac` 會檢查 `API_KEY`、`SECRET_KEY`、`CA_CERT_PATH`、`CA_PASSWORD`，缺了就印出缺哪些並 exit 1。arenax 不需要任何設定檔。
- 不會自己啟動 ArenaX，要先跑 `uv run arenaxd`。連線位址取 `ARENAX_HOST`（localhost）與 `ARENAX_PORT`（8801）。

| `--broker` | 行為 |
|---|---|
| `arenax` | 連 ArenaX，`api_key` 固定 `testkey123` |
| `sinopac` | 永豐；`SIMULATION=y` 進模擬環境；mirror DB 在 `<data>/mirrors/sinopac_<USERNAME>.db` |
| `arenax_legacy` | ArenaX ＋ 永豐真實帳戶，需要永豐憑證（不檢查是否缺 key） |
| `cathay`、`ibkr`、`mega` | 印「coming soon」後離開 |
| 其他 | 印支援清單後離開（exit 0） |

`mock`、`realistic` 與 `BrokerType.MOCK` 已移除；`BrokerType` 現在是 `SINOPAC`、`YUANTA`、`CATHAY`、`ARENAX`（後兩個以外的元大、國泰會丟 `NotImplementedError`）。

`-B` 之後還有參數時執行單一指令（非互動），指令失敗 exit 1：`uv run cjshell -B arenax lspos`。

### 指令

| 指令 | 說明 |
|---|---|
| `help [command]` | 列出指令或單一指令說明 |
| `date [year\|YYYY-MM-DD\|+N\|-N]` | 顯示目前（模擬）時間與月曆；`+N`/`-N` 把 ArenaX 時鐘往前／後移 N 小時（`PATCH /api/v1/clock`，維持原本的暫停狀態），只在 arenax 可用 |
| `buy <symbol> <price> <quantity> [intraday_odd]` | 買進 |
| `sell <symbol> <price> <quantity> [intraday_odd]` | 賣出 |
| `ohlcv <symbol> [...]` | 一或多檔快照 |
| `rank` | 漲跌排行 |
| `bidask <symbol> [intraday_odd]` | 五檔 |
| `lsodr [num_result]` | 列委託 |
| `lspos` | 列部位 |
| `start <symbol> <buy_target_price> <sell_target_price> <delay>` | 跑固定價格分析策略 |
| `balance` | 帳戶餘額 |
| `news [days]` | 近期重大公告 |
| `search <keyword...>` | 搜尋網路新聞（NewsAPI 用 `NEWSAPI_API_KEY`） |
| `kbars <symbol>` | K 線 |
| `llm <prompt>` | 呼叫 LLM（Azure OpenAI 環境變數） |
| `replay <symbol> <range> <interval>` | 回放歷史 K 線並在瀏覽器畫圖 |
| `cancel` | 取消所有未成交委託 |
| `clear` | 清畫面 |
| `system [cmd...]` | 不帶參數印 OS 資訊；帶參數用 shell 執行該指令 |
| `info` | 顯示版本（`cjtrade.__version__`，在 checkout 裡另附 commit）、連線券商與新聞來源 |
| `exit` | 離開 |

```sh
uv run arenaxd &
uv run cjshell -B arenax
uv run cjshell -B arenax ohlcv 2330 0050
uv run cjshell -B arenax date +24
```

---

## `cjtrade`：CJTrade 交易引擎

入口：`cjtrade.apps.CJTrade.main:cli`（`src/cjtrade/apps/CJTrade/`）。一個 master 程序持有券商連線與 RiskGate，每根 1m K 棒透過 ZMQ（PUB `tcp://127.0.0.1:5555`、PULL `tcp://127.0.0.1:5556`）發給各 bot 子程序；bot 回傳 OrderIntent，master 決定是否下單。bot 以模組方式啟動：`python -u -m cjtrade.apps.CJTrade.bot_x <bot_id> <balance> <session_id> <symbol> [extra...]`，連續 180 秒沒收到資料會自行結束。

### 前置

引擎不會啟動 ArenaX。連線 port 是 `ARENAX_PORT`，沒設就依 `--mode`：demo 8801、backtest 8802、paper 8803。

```sh
uv run arenaxd --backend=backtest --data=finmind,yfinance > /dev/null 2>&1 &
sleep 15
uv run cjtrade --broker=arenax --mode=backtest --watch-list=2357 \
  --fund=1000000 --days=30 --start-date=2025-09-01 --speed=0
```

### 參數（表單 `src/cjtrade/apps/CJTrade/form.toml`，CLI renderer）

FormEngine 掃描 `sys.argv`，接受 `--flag value`、`--flag=value`。命令列有給的欄位不再詢問，其餘會在終端機提問（預設值來自 `<state>/form_state/form.json` 記住的答案）。要完全不互動就七個都給。

| `cli_arg` | 欄位 | 預設 | 引擎實際用途 |
|---|---|---|---|
| `--broker` | broker（arenax、sinopac） | arenax | 只接受 `arenax`；其他值印錯誤後結束 |
| `--mode` | mode（backtest、paper、demo） | backtest | 決定預設 port；paper 改用 realtime 時鐘 |
| `--speed` | playback_speed（0、0.5 … 30000） | 1200 | 每真實秒走幾個市場秒；`0` = 全速；paper 忽略 |
| `--watch-list` | watch_list | 記住的值 | 逗號分隔；空的話引擎直接結束 |
| `--fund` | fund | 500000 | 不設定餘額；和券商餘額不同時印警告，提示用 `AX_INITIAL_BALANCE` 啟動 `arenaxd`。bot 依券商實際餘額下單 |
| `--days` | days | 365 | 回放天數，區間 `[start, start+days)` |
| `--start-date` | start_date（選填） | 空 = 用伺服器的時間軸起點 | |

另外一個不經過表單的旗標：`--roster=PATH`（必須是 `=` 形式）。

### `--roster` 格式

JSON 陣列，每個元素：

```json
[{"bot_id": "Bot_U1", "script": "bot_custom.py", "symbol": "2317",
  "extra": ["/path/to/strategy.py"]}]
```

`bot_id` 不可重複；`script` 必須是 `src/cjtrade/apps/CJTrade/` 下的 `bot_*.py`；`symbol` 不在 watch list 的 bot 不會啟動；檔案有問題時整個 run 直接中止，不會改用預設名單。沒給 `--roster` 時用 `main.py` 內的 `BOT_ROSTER`（只啟用 `Bot_B`，2357）。

### CLOCK 模式

模組常數 `CLOCK`（預設 `"replay"`），要改就編輯 `main.py`。`--mode` 是 paper 或 real 時一律改用 realtime。

| 值 | 行為 |
|---|---|
| `replay` | 以 `GET /api/v1/clock/timeline` 的時間戳為唯一時間來源，引擎每步用 `PATCH /api/v1/clock` 推進；同資料兩次執行結果相同 |
| `scaled` | ArenaX 自己跑時鐘，引擎依伺服器 `playback_speed` 取樣 |
| `realtime` | 60 秒市場時間 = 60 秒真實時間，不碰券商控制面 |

其他寫在檔案裡的常數：`RISK_MAX_ORDERS_PER_BAR=3`、`RISK_MAX_LOSS_PCT=0.25`、`RISK_DUPLICATE_WINDOW_BARS=3`、`ACCOUNT_READ_MAX_FAILURES=5`、`BOT_SILENT_BARS=20`、`BOT_HANDSHAKE_TIMEOUT_S=30`、`BAR_BARRIER_TIMEOUT_S=30`。每個 bot 分到的資金 = 券商餘額 ÷ 實際啟動的 bot 數。

### 狀態 API（`status_api.py`，固定 127.0.0.1，port `CJ_ENGINE_STATUS_PORT` 或 8898）

會檢查 Host header，不送 CORS header。有設 `CJ_ENGINE_CONTROL_TOKEN` 時，所有路由都要 `Authorization: Bearer <token>`；沒設時讀取開放、寫入回 503。

| 路由 | 說明 |
|---|---|
| `GET /health` | 存活 |
| `GET /status` | run 狀態總覽 |
| `GET /bots` | 各 bot 狀態 |
| `GET /bots/{bot_id}/history?limit=N` | 該 bot 每根 K 棒的回報（`limit=0` 全部） |
| `GET /equity?limit=N` | 權益曲線，預設最後 1000 點，`limit=0` 全部 |
| `GET /roundtrips` | 已完成的買賣來回（快取 2 秒） |
| `POST /bots/{bot_id}/stop` | 停止一個 bot 並撤回其掛單；沒設 token 時回 503 |

```sh
curl -s http://127.0.0.1:8898/status
```

### Bots

| 檔案 | 策略 | 預設 symbol | 重點參數 |
|---|---|---|---|
| `bot_a.py` | `DCA_Monthly` 每月定額、不賣 | 0050 | `dca__amount=10000` |
| `bot_b.py` | `ADXAdaptiveStrategy` 趨勢／盤整切換 | 2357 | `adx__*`、`risk__max_position_pct=0.20` |
| `bot_c.py` | `BollingerStrategy` 均值回歸 | 2317 | `bb__window_size=100`、`bb__min_width_pct=0.01`、`risk__max_position_pct=0.20` |
| `bot_custom.py` | 載入使用者寫的策略檔 | 2317 | `risk__max_position_pct=0.20` |

共用邏輯在 `bot_runner.py`，訊息格式在 `protocol.py`。

### 跑自訂策略

1. 用 `cjtrade.pkgs.strategy.authoring` 寫一個檔案：定義 `on_bar(bar, account)`，回傳 `buy()`、`sell()` 或 `hold()`；`init`、`on_fill`、`on_end` 選填；參數用 `param.int(...)`、`param.float(...)`，指標用 `ta.*`。
2. 檢查：`uv run strategy-tool check --file my_strategy.py`。
3. 寫 roster 並執行：

```sh
uv run strategy-tool template --kind bb      # 起手範本（JSON 的 source 欄位）
cat > /tmp/roster.json <<'EOF'
[{"bot_id": "Bot_U1", "script": "bot_custom.py", "symbol": "2317", "extra": ["/abs/path/my_strategy.py"]}]
EOF
uv run cjtrade --roster=/tmp/roster.json \
  --broker=arenax --mode=backtest --watch-list=2317 --fund=1000000 \
  --days=30 --start-date=2025-09-01 --speed=0
```

### 輸出

`<reports>/engine_<sid8>.equity.jsonl`（執行中寫入）、`engine_<sid8>.pkl`、`engine_<sid8>.html`。之後用 `uv run insight` 分析。log 只印到 stdout/stderr（FinHub 起的 run 會存到 `<data>/finhub/run_logs/`）。

---

## `finhub`：FinHub 網頁介面

入口：`cjtrade.apps.FinHub.main:cli`（`src/cjtrade/apps/FinHub/`，FastAPI + uvicorn）。需要 `cjtrade[finhub]` extra；在 checkout 裡 `uv sync` 會裝（dev group 含 `cjtrade[all]`）。

| 選項 | 預設 | 說明 |
|---|---|---|
| `--port N` | 8000 | 固定綁 `127.0.0.1`，沒有改 host 的選項 |
| `--reload` | — | 程式碼變動時重啟（開發用） |

開 <http://127.0.0.1:8000>，註冊帳號後登入。開新 run 時，FinHub 先看 ArenaX port（預設 8802）有沒有伺服器在跑：沒有就用 `python -m cjtrade.apps.ArenaX.brokerside_server --backend=<mode> --port=<port>` 起一個（帶 `AX_BACKTEST_PLAYBACK_SPEED`、`AX_BACKTEST_DURATION_DAYS=days+1`、`AX_INITIAL_BALANCE=fund`），有就直接沿用；再用 `python -m cjtrade.apps.CJTrade.main` 帶齊七個表單旗標（有自選策略時加 `--roster=`）起引擎，並設 `CJ_ENGINE_STATUS_PORT`、`ARENAX_PORT`、隨機產生的 `CJ_ENGINE_CONTROL_TOKEN`。run 的 mode 只能是 backtest、paper、demo。一次只能跑一個 run（ZMQ port 固定）。

要從別台機器用：`ssh -L 8000:127.0.0.1:8000 <host>`。

### 設定（`config.py`）

環境變數加 `FINHUB_` 前綴，或寫在 `<config dir>/finhub.env`。全部選填。

| 變數 | 預設 | 說明 |
|---|---|---|
| `FINHUB_SECRET_KEY` | 每個程序隨機產生 | 簽 session token；沒設的話重啟後全部登出（啟動時會印產生指令） |
| `FINHUB_ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | |
| `FINHUB_DATABASE_URL` | `sqlite:///<data>/finhub/finhub.db` | `postgres://` 會自動改成 `postgresql://` |
| `FINHUB_ENGINE_STATUS_HOST` / `FINHUB_ENGINE_STATUS_PORT` | 127.0.0.1 / 8898 | 引擎狀態 API |
| `FINHUB_ARENAX_HOST` / `FINHUB_ARENAX_PORT` | 127.0.0.1 / 8802 | run 用的 ArenaX（所有 mode 共用這個 port） |
| `FINHUB_ARENAX_API_KEY` | `testkey123` | |
| `FINHUB_PYTHON` | 目前的直譯器 | 用來起 arenaxd、引擎、strategy-tool |
| `FINHUB_RUN_LOG_DIR` | `<data>/finhub/run_logs` | |

ArenaX 子程序繼承 FinHub 的環境，所以 `AX_*` 可直接傳：

```sh
AX_DATA_SOURCES=offline AX_PRICE_DB_PATH=exp.db uv run finhub
```

### 頁面與 API

頁面：Positions、Orders、Manual Trade、Market（快照、歷史 K 線、模擬時鐘）、Runs、Bots、Strategies（內建 CodeMirror 編輯器）、Risk gate。API 在 `/api/v1/`：`auth/*`、`engine/*`（轉呼叫 8898）、`broker/*`（轉呼叫 ArenaX，含手動下單與全部取消）、`runs`、`strategies`（含 `check`、`templates`、`seed-examples`、啟停）、`supervisor`、`audit`。手動下單直接送 ArenaX，不經引擎的 RiskGate，並以 `opt_field.source = "finhub-manual"` 標記。停用某個策略時會呼叫引擎的 `POST /bots/{id}/stop`。

```sh
uv run finhub
uv run finhub --port 8010
uv run pytest tests/unit/apps/FinHub -q
```

---

## `backtest`：One-shot 回測

入口：`cjtrade.apps.oneshot_backtest:main`（`src/cjtrade/apps/oneshot_backtest.py`）。一次從 ArenaX 取全部 K 線，在記憶體跑策略。只讀 `ARENAX_PORT` 一個環境變數（預設 8801）；ArenaX 用 backtest 模式（8802）時要設 `ARENAX_PORT=8802`。

| 選項 | 預設 | 說明 |
|---|---|---|
| `--symbol` | 必填 | 例 `2330` 或 `2330,0050` |
| `--start` | 隨機（今天往前 duration+7 到 10 年之間） | `YYYY-MM-DD` |
| `--duration` | 365 | 日曆天 |
| `--interval {1m,5m,1h,1d}` | `1d` | |
| `--balance` | 1000000 | |
| `--strategy` | `BollingerStrategy` | 另有 `SupportResistanceStrategy`、`DCA_Monthly`、`DonchianBreakoutStrategy`、`ADXAdaptiveStrategy`、`BaselineStrategy` |
| `--params` | — | `'bb__window_size:30,risk__max_position_pct:0.1'` |
| `--show-params` | — | 印參數設定後離開 |
| `--compare` | — | 六種策略一起跑並輸出比較 |
| `--no-browser` | — | 不開瀏覽器 |

輸出：`<reports>/oneshot_<label>_<sid8>.pkl` 與 `.html`，最後印 `insight <sid8>`。`--compare` 的 `comparison_*.html`、`compare_returns_*.html`、`compare_equity_*.html`、`fullreport_*.html` 也寫在 `<reports>`。

```sh
uv run arenaxd &
uv run backtest --symbol 2330 --start 2024-01-01 --duration 180 --no-browser
uv run backtest --symbol 2330 --show-params --interval 1d
```

---

## `preload-prices`

入口：`cjtrade.apps.preload_prices:main`。把 K 線下載進 SQLite 快取，供離線 ArenaX 使用。只抓缺的區間，重跑等於補齊。

| 選項 | 預設 | 說明 |
|---|---|---|
| `--symbols` | 必填 | 逗號分隔 |
| `--start` | 必填 | `YYYY-MM-DD` |
| `--end` | 明天 | 不含當日（半開區間） |
| `--interval` | `1m,5m,1h,1d` | 可選 `1m,5m,15m,30m,1h,1d` |
| `--data` | `finmind,yfinance` | 含 `sinopac` 時會登入永豐；不接受 `offline`／只有 `cache` |
| `--price-db` | `<cache>/arenax_price.db` | |

```sh
uv run preload-prices --symbols 2330,2317 --start 2025-09-01 --end 2025-10-01 --price-db exp.db
```

## `insight`

入口：`cjtrade.apps.insight:main`。讀 `<reports>/oneshot_*.pkl` 或 `engine_*.pkl`，配合本機價格快取，寫出 `<stem>.insight.md` 與 `<stem>.insight.json`。

| 選項 | 說明 |
|---|---|
| `run`（位置參數） | session id、唯一前綴，或 pkl 路徑；省略 = 最近一次 |
| `--list` | 列出本機所有 run |
| `--out DIR` | 輸出到別的目錄 |
| `--stdout` | 同時印出 markdown |

```sh
uv run insight
uv run insight --list
uv run insight 51702f96 --stdout
```

## `strategy-tool`

入口：`cjtrade.apps.strategy_tool:main`。輸出一律是一個 JSON 物件；只要問題有被回答就 exit 0（包括「策略有錯」）。FinHub 的策略頁也是呼叫它。

| 子指令 | 選項 | 說明 |
|---|---|---|
| `templates` | — | 範本清單 |
| `template` | `--kind {bb,dca,adx,blank}`（預設 bb）、`--name`（My strategy）、`--symbol`（2317） | 產生完整範本原始碼 |
| `check` | `--file PATH`（預設讀 stdin） | 診斷與宣告的參數 |
| `api` | — | 策略可用的所有名稱 |

```sh
uv run strategy-tool templates
uv run strategy-tool template --kind dca --name "My savings" --symbol 0050
uv run strategy-tool check < my_strategy.py
```

---

## `poc/backtest.sh`：表單驅動的 one-shot 回測

1. 用 FormEngine 跑 `poc/backtest.toml`（以腳本所在目錄找，任何目錄都找得到），再用 `poc/strategy_params.py` 問該策略的參數。
2. 檢查必填變數；表單沒完成就結束。
3. 依 mode 設 `ARENAX_PORT`（backtest 8802、paper 8803、其他 8801），伺服器沒在跑就 `uv run arenaxd --backend=$ARENAX_MODE`（結束時關掉）。
4. 執行 `python -m cjtrade.apps.oneshot_backtest`。

腳本自己處理的旗標：

| 旗標 | 說明 |
|---|---|
| `--renderer=cli\|web\|zenity\|auto` | 預設 `web`（本機 127.0.0.1:9876 並開瀏覽器），兩個表單共用 |
| `--show-params` | 直接印 1d 參數後離開 |

表單欄位旗標（`poc/backtest.toml`）：

| `cli_arg` | 輸出變數 | 預設 |
|---|---|---|
| `--watch-list` | `CJSYS_WATCH_LIST` | 記住的值 |
| `--fund` | `INITIAL_FUND` | 500000 |
| `--start` | `START_DATE` | 空 = 隨機 |
| `--days` | `DURATION_DAYS` | 365 |
| `--interval` | `INTERVAL` | `1m` |
| `--mode`（backtest、paper、demo） | `ARENAX_MODE` | backtest |
| `--strategy` | `STRATEGY` | BollingerStrategy |
| `--compare` | `COMPARE_MODE` | false |

`poc/strategy_params.py` 選項：`--strategy`（必填）、`--interval {1m,5m,1h,1d}`（必填）、`--params`、`--renderer`（預設 web）。輸出 `export PARAMS=...`。

需要 `curl` 與 `jq`。`poc/backtest_full_simulation.sh/.toml` 與 `poc/StrategyEditor.sh` 已刪除。

```sh
bash poc/backtest.sh --renderer=cli
bash poc/backtest.sh --renderer=cli --watch-list 2330 --fund 1000000 --start 2024-01-01 \
  --days 180 --interval 1d --mode demo --strategy BollingerStrategy
```

---

## `scripts/`

| 腳本 | 用法 | 說明 |
|---|---|---|
| `gen_config.sh` / `gen_config.bat` | `bash scripts/gen_config.sh {arenax\|sinopac}` | 在目前目錄產生 `<template>_system.cjconf`；檔案已存在時會互動詢問是否覆蓋 |
| `gen_init_account.sh` / `.bat` | `bash scripts/gen_init_account.sh <broker> [balance]` | 產生 `<broker>_<USERNAME>.json` 帳戶快照（balance 預設 10000）；需要 `jq` |
| `gen_todos_report.sh` | `bash scripts/gen_todos_report.sh` | 用 `git grep TODO` 產生 `todos_report_for_<tag 或 commit>.md` 到 repo 根目錄 |
| `check_readme_examples.py` | 見下方 | README 範例檢查 |
| `price_db_report.py` | 見下方 | 價格快取報告 |
| `quick_imports.py` | 在 REPL 裡 `exec(open('scripts/quick_imports.py').read())`（repo 根目錄） | 匯入常用模組並提供 `get_client()`；只支援永豐，且 `simulation` 寫死 False |

### `scripts/check_readme_examples.py`

檢查清單中的 README（`README.md`、`src/cjtrade/README.md`、`src/cjtrade/apps/README.md` 與 ArenaX、CJEdit、CJNews、CJShell、CJTrade、FinHub、`pkgs/brokers` 的 README）。每個 code block 前一行都要有標記，沒標記就算錯：

- `<!-- cjcheck: smoke -->`、`<!-- cjcheck: smoke timeout=20 -->`：啟動，不可在一開始就死掉（逾時仍在跑算通過）
- `<!-- cjcheck: run -->`：必須 exit 0
- `<!-- cjcheck: static -->`：不啟動，只檢查 `uv run NAME` 存在且目標函式存在、路徑存在、`--flag` 被接受、已知 port 的 URL 路由存在（8801–8803 是 ArenaX，8898 是引擎）、python block 可解析
- `<!-- cjcheck: skip reason="..." -->`：排除

| 選項 | 說明 |
|---|---|
| `--no-smoke` | 只做靜態檢查（等同 `CJ_CHECK_NO_SMOKE=1`），不到一秒、不需網路 |
| `--list` | 列出每個 block 與檢查方式 |

本次快照執行 `--no-smoke` 結果：41 個 block，37 檢查、4 skip，全部通過。

```sh
uv run python scripts/check_readme_examples.py --no-smoke
uv run python scripts/check_readme_examples.py
```

### `scripts/price_db_report.py`

唯讀（`mode=ro`）開啟價格快取，印出每檔的時間軸與缺口，並稽核「有 coverage 紀錄但沒有 K 棒」的區段。可以對執行中的伺服器使用。

| 選項 | 預設 | 說明 |
|---|---|---|
| `-s/--symbol` | 全部 | 單一代號細節 |
| `-t/--timeframe` | `1m` | |
| `--from` / `--to` | — | `YYYY-MM-DD`，`--to` 不含 |
| `--width` | 依終端機寬度 | |
| `--months` | — | 加月表 |
| `--days` | — | 列出每一天 |
| `--min-bars` | 243（270 的 90%） | 1m 一天少於此算不足 |
| `--db` | `AX_PRICE_DB_PATH`，再退回 `<cache>/arenax_price.db` | |

```sh
uv run python scripts/price_db_report.py
uv run python scripts/price_db_report.py -s 2317 --months --days
uv run python scripts/price_db_report.py --db exp.db
```

---

## 開發流程

### 測試

`pyproject.toml` 設定 `testpaths = ["tests/unit", "tests/integration"]`、`addopts = "-v --tb=short"`。`tests/manual/` 不會被收集（需要真券商）。`tests/conftest.py` 依所在目錄自動加上 `unit` 或 `integration` marker。`tests/integration/arenax` 在 `localhost:8801` 沒有服務時會自動 skip；`tests/integration/cjtrade` 會自己起 arenaxd（8802，offline），用 repo 內 2357 的 10 天 1m 資料跑 `cjtrade`，逐筆比對成交，約 45 秒。

```sh
uv run pytest                                       # unit + integration
uv run pytest -m "not integration"
uv run pytest tests/unit/ --cov=src/cjtrade --cov-report=term-missing
bash tests/run_broker_stability_tests.sh --broker=arenax --coverage
uv run pytest tests/integration/cjtrade             # 引擎端到端，不需網路
```

| 指令 | 說明 |
|---|---|
| `bash tests/run_broker_stability_tests.sh [--broker=arenax] [--coverage]` | 在 repo 根目錄覆寫 `backtest_account_state.json` 與 `demo_account_state.json`，必要時起 `uv run arenaxd`（demo），跑 `tests/integration/<broker>`；輸出 `LAST_BROKER_STABILITY_TEST.log`、`htmlcov/integration_<broker>`；需要 `jq` |
| `bash tests/test_cjtrade_integration_arenax.sh --broker=arenax --group=all` | 必要時起 `uv run arenaxd`（demo，8801），再逐一執行 `cjshell.py --broker=arenax` 的指令；需要 `curl`、`jq`；`--broker` 預設 arenax |
| `bash tests/test_cjtrade_integration.sh --broker=sinopac --group=all` | 對 `cjshell_legacy.py` 跑同一組指令。`--broker` 必填（不給就 exit 1），因為 sinopac 會**下真單**；沒有 `SIMULATION=y` 時就是正式帳戶 |
| `bash tests/find_bad_commit.sh --good <sha> --bad <sha> --script <cmd>` | `git bisect run` 包裝；缺參數會互動詢問 |

兩支 shell 測試的選項：`--broker=<name>`、`--group={trading,query,market,system,news,all}`（預設 all）、`--continue-on-error`、`--no-log`、`-h`。log 寫到 `LAST_CJTRADE_INTEGRATION_TEST.log`。

`tests/manual/`（例如 `test_cjtrade_shell_all_cmds.sh`）與 `src/cjtrade/apps/ArenaX/tests/`（`test_server_time.sh`、`price_downloader.py`）是手動腳本，需要真券商或會自己起伺服器，不在 CI 中。

### pre-commit（`.pre-commit-config.yaml`）

安裝：`uv run pre-commit install`。本地 hook 都是 `pass_filenames: false`，所以每次 commit 都會完整執行。

| Hook id | 執行內容 |
|---|---|
| `trailing-whitespace`、`end-of-file-fixer`、`check-yaml` | pre-commit-hooks v4.6.0 |
| `reorder-python-imports` | v3.16.0 |
| `docs-readme` | `uv run python scripts/check_readme_examples.py`（smoke 模式會啟動範例，需網路） |
| `unit` | `uv run pytest tests/unit/ --tb=short -q --cov=src/cjtrade --cov-report=term-missing --cov-report=html:htmlcov/unit` |
| `integration-arenax` | `bash tests/run_broker_stability_tests.sh --broker=arenax --coverage`（會起 arenaxd，yfinance 需網路） |
| `integration-engine` | `uv run pytest tests/integration/cjtrade -q`（起 arenaxd 8802，offline） |
| `integration-cjshell-arenax` | `bash tests/test_cjtrade_integration_arenax.sh --broker=arenax --group=all` |
| `integration-cjshell-sinopac` | `bash tests/test_cjtrade_integration.sh --broker=sinopac --group=all`（會登入永豐並下**真單**） |

命名規則：hook id 是 `類別-對象`，name 是動詞開頭的一句話（`Run the unit tests`）；CI 的 job 用同一個 id，name 是 `類別: 對象`（`unit: tests/unit`、`integration: ArenaX API`）。

跳過特定 hook 用 `SKIP`（逗號分隔 hook id）：

```sh
SKIP=integration-cjshell-sinopac git commit -m "..."
SKIP=integration-cjshell-sinopac,integration-cjshell-arenax,integration-arenax git commit -m "..."
CJ_CHECK_NO_SMOKE=1 SKIP=integration-cjshell-sinopac git commit -m "..."
```

### 文件

`mkdocs.yml` 的 `docs_dir` 是 `doc/`，`strict: true`。英文頁是 `name.md`，繁中頁是 `name.zh-TW.md`。

```sh
uv run --group docs mkdocs serve                  # http://127.0.0.1:8000
uv run --group docs mkdocs build --strict --site-dir site
```

FinHub 預設也是 8000，兩者同時開時其中一個要換 port（例如 `uv run finhub --port 8010`）。

### CI（`.github/workflows/`）

| Workflow | 觸發 | 內容 |
|---|---|---|
| `ci.yml` | push、pull_request、手動 | 各 hook 一個同名 job：`lint`（只對本次變更檔案跑 whitespace/EOF/YAML/import order）、`docs-readme`、`unit`（上傳 `htmlcov/unit`）、`integration-arenax`、`integration-engine`、`integration-cjshell-arenax`、`integration-cjshell-sinopac`（需 `SINOPAC_API_KEY`、`SINOPAC_SECRET_KEY`、`SINOPAC_CA_CERT_BASE64`、`SINOPAC_CA_PASSWORD` secrets，缺就跳過；強制 `SIMULATION=y`，所以 CI 只下沙盒單；fork 的 PR 不跑；同時只允許一個 Sinopac 登入）。全部 `TZ=Asia/Taipei`、Python 3.12、`UV_LOCKED=1` |
| `codeql.yml` | 對 `master` 的 push/PR、每週一 03:17（台北）、手動 | CodeQL `security-extended`，語言 python、actions 與 javascript-typescript；忽略 `poc/experiments`、`ref`、`tests`、`src/cjtrade/apps/FinHub/static/vendor` |
| `docs.yml` | push、pull_request、手動 | `uv sync --locked --only-group docs` 後 `mkdocs build --strict`；只有 `master` 的 push 會部署到 GitHub Pages |
| `labeler.yml` | `pull_request_target` | 依分支名與變更檔案自動加 label（規則在 `.github/labeler.yml`，label 定義在 `.github/labels.yml`） |
| `labels.yml` | `master` 上 `.github/labels.yml` 有變動、手動 | 依 `labels.yml` 建立或更新 label，不刪除 |
| `release.yml` | push `v*` tag | 檢查 tag 與 `pyproject.toml` 版本一致 → build → 驗證 wheel 能裝能 import → 用 Trusted Publishing 上傳 PyPI（`pypi` environment）→ 建立 GitHub Release，附 sdist／wheel，release notes 依 `.github/release.yml` 按 label 分類 |

Dependabot（`.github/dependabot.yml`）：每週一 09:00（台北）對 GitHub Actions 與 uv 依賴各開一張合併 PR（Python 的 major 版本各自一張），每月對 pre-commit hook 開一張；標題前綴 `[chore]:`，自動加 `chore`／`dependencies` 等 label。

### 發布新版本

1. 把 `pyproject.toml` 的 `version` 改成新版本（例如 `1.0.0`），照平常流程開 PR 並 merge。
2. 在 master 上打 tag 並推上去：

   ```sh
   git switch master && git pull
   git tag -a v1.0.0 -m "v1.0.0"
   git push origin v1.0.0
   ```

3. `release.yml` 會自動上傳 PyPI 並建立 GitHub Release。tag 與版本不一致時第一步就失敗，什麼都不會發布。PyPI 不接受重複上傳同一個版本，發錯只能再發一個新版本。

---

## 小型 app

### CJEdit

```sh
uv run python src/cjtrade/apps/CJEdit/main.py
```

在終端機用表單（`pages/index.toml`，CLI renderer）問：編輯器（gedit、nano、vim、vscode、sublime，預設 vscode）、broker（預設 arenax）、ArenaX backend（`--`、demo、backtest、paper）、project type（目前沒有作用）。之後把對應的 import 範本寫進暫存檔 `cjedit_*.py`，用選定的編輯器開啟，最後印出 `<目前的 python> <檔案>` 執行指令。沒有命令列選項。

### CJNews

```sh
uv run python src/cjtrade/apps/CJNews/main.py
```

用 web 表單（127.0.0.1:9876，會開瀏覽器）問關鍵字（預設 台積電）、來源（CNYES 鉅亨網、NewsAPI）、筆數（1 到 20，預設 5），結果也用 web 表單顯示。NewsAPI 需要 `NEWSAPI_API_KEY`，沒設就結束並提示。關鍵字沒結果時改抓頭條。沒有命令列選項。

### `python -m cjtrade.pkgs.ui`

```sh
uv run python -m cjtrade.pkgs.ui poc/backtest.toml --renderer=cli
```

通用表單執行器：位置參數是 TOML，`--renderer`（預設 `auto`：有 zenity 用 zenity，否則 cli），輸出 `export VAR='...'` 供 `eval`。不接受欄位旗標（用 `parse_args()`）。`poc/backtest.sh` 改用 `python -c` 直接呼叫 FormEngine，所以不受影響。

### `poc/experiments/`（研究用，原 `exp/`）

`PROTOCOL.md` 是實驗規範，`PROMPT` 是給代理的指示，`strategies/example_breakout.py` 是範例策略。腳本在 `poc/experiments/bin/`：

| 腳本 | 用法 |
|---|---|
| `run.sh` | `./poc/experiments/bin/run.sh <tag> <symbol> <strategy> <interval> <start> <duration> [params]`；strategy 是 `.py` 路徑時改用 `custom_backtest.py`；環境 `BAL`（1000000）、`ARENAX_PORT`（8802）、`EXPECT_BARS`；跑回測＋insight，追加到 `poc/experiments/runs.csv`，報告放 `poc/experiments/runs/<tag>/` |
| `custom_backtest.py` | `--file`（必填）、`--class`、`--symbol`（必填）、`--start`（必填）、`--duration`（必填）、`--interval`（1m）、`--balance`、`--params`；用自寫的 BaseStrategy 跑 one-shot |
| `prewarm.sh` | `./poc/experiments/bin/prewarm.sh <tf> <symbol...>`；環境 `ARENAX_PORT`（8802）、`PREWARM_SLEEP`（2）；逐年預熱價格快取 |
| `prewarm_one.py` | `python poc/experiments/bin/prewarm_one.py <sym> <tf> <start> <end>` |
| `report.sh` | `./poc/experiments/bin/report.sh [tag\|--pass\|--bad]`，讀 `poc/experiments/runs.csv` |
| `windows.sh` | `./poc/experiments/bin/windows.sh {is,oos,is-seg,oos-seg,stress-seg}`，印預先登記的評估視窗；日期運算改用 python3，macOS 與 Linux 都能跑 |

---

## 常用情境

### 不用券商帳號跑回測

```sh
uv run arenaxd --backend=backtest --data=finmind,yfinance > /dev/null 2>&1 &
sleep 15
ARENAX_PORT=8802 uv run backtest --symbol 2330 --start 2024-01-01 --duration 180 --no-browser
```

或用 demo 模式（yfinance，8801，日線最穩；yfinance 的分線只有近 30 天左右）：

```sh
uv run arenaxd &
uv run backtest --symbol 2330 --duration 180
```

### 用網頁跑回測（FinHub）

```sh
AX_DATA_SOURCES=finmind,yfinance uv run finhub
```

開 <http://127.0.0.1:8000>，註冊、登入，在 Runs → New Run 開始。不設 `AX_DATA_SOURCES` 的話，FinHub 起的 backtest 伺服器會用預設的 `sinopac,yfinance`，需要永豐登入。

### 離線實驗

```sh
uv run preload-prices --price-db exp.db --symbols 2317 --start 2025-09-01 --end 2025-10-01
uv run python scripts/price_db_report.py --db exp.db -s 2317
CJTRADE_OFFLINE=1 uv run arenaxd --backend=backtest --data=offline --price-db=exp.db &
```

要完全和預設資料隔離，再加上 `CJTRADE_HOME=/tmp/cj-exp`。

### 用命令列跑交易引擎回測

```sh
AX_INITIAL_BALANCE=1000000 uv run arenaxd --backend=backtest --data=finmind,yfinance > /dev/null 2>&1 &
sleep 15
uv run cjtrade --broker=arenax --mode=backtest \
  --watch-list=2357 --fund=1000000 --days=30 --start-date=2025-09-01 --speed=0
curl -s http://127.0.0.1:8898/status      # 執行中另開終端機查看
```

watch list 必須包含 roster 裡 bot 的 symbol（預設 Bot_B 是 2357）。`--fund` 和 `AX_INITIAL_BALANCE` 不一致時引擎會警告。

### 看回測結果

```sh
uv run insight --list
uv run insight                # 最近一次
uv run insight <sid前綴> --stdout
```

HTML 與 pkl 在 `<data>/reports/`（macOS：`~/Library/Application Support/cjtrade/reports/`）。

### 檢查 README

```sh
uv run python scripts/check_readme_examples.py --no-smoke   # 快、離線
uv run python scripts/check_readme_examples.py --list
uv run python scripts/check_readme_examples.py              # 會實際啟動範例
```

### 送 commit 前

```sh
uv run pytest tests/unit/ -q
uv run python scripts/check_readme_examples.py --no-smoke
SKIP=integration-cjshell-sinopac git commit -m "..."
```

沒有永豐憑證，或不想下真單時，一定要 `SKIP=integration-cjshell-sinopac`。離線時再加 `integration-cjshell-arenax,integration-arenax` 與 `CJ_CHECK_NO_SMOKE=1`。

---

## 已修正

前一版列出的問題，依目前程式碼確認的狀態：

1. **legacy mock broker**：`mock`、`realistic`、`BrokerType.MOCK` 與依賴它們的入口一起移除；`gen_config.sh`／`.bat` 只剩 arenax、sinopac。
2. **shell 一定要永豐環境變數**：`cjshell -B arenax` 不再需要任何憑證；只有 sinopac 會檢查並列出缺的 key。
3. **`info` 不顯示版本、`date +N/-N` 未實作**：`info` 印 `cjtrade.__version__`（checkout 內附 commit）；`date +N/-N` 透過 `PATCH /api/v1/clock` 移動 ArenaX 時鐘 N 小時。
4. **shell 測試**：`test`／`atest` 移除，改直接跑兩支 shell 腳本；sinopac 那支的 `--broker` 改為必填。
5. **`aresh` 只能連 8801**：新增 `--host`／`--port`，預設讀 `ARENAX_HOST`／`ARENAX_PORT`。
6. **`system` 沒有對應設定檔**、7. **`system` 不讀 `AX_*` 且會 SIGKILL 佔用 port 的程序**、8. **`system` 固定指定 `CJSYS_STATE_FILE`**：`apps/cjtrade_system` 整個刪除，三項都不存在了。
9. **`AX_SKIP_DATA_PRELOAD = n` 被當成 true**：改用 `_flag()` 解析成 bool。
10. **讀了沒用的 `AX_*` key**：四個 key 從 cjsys 檔移除，`load_cjsys` 也不再讀它們。
11. **`backtest` docstring 與 `--symbol`**：docstring 不再列 `CJSYS_ONESHOT_*`；`--symbol` 改為 argparse 必填；`--compare` 的 HTML 都寫到 `<reports>`。
12. **`backtest_full_simulation.sh` 帶旗標失敗**、13. **使用舊路徑**、14. **`StrategyEditor.sh` 失效**：三個檔案都已刪除。
15. **`poc/backtest.sh` 加兩次 `--start`**：只加一次；`backtest.toml` 依腳本位置尋找。
16. **交易引擎旗標沒作用**：ArenaX port 改為 `$ARENAX_PORT` 或依 mode 的預設；`--broker` 非 arenax 會被拒絕；`--fund` 與券商餘額不同時提示用 `AX_INITIAL_BALANCE`；`BOT_ROSTER` 註解與實際一致（只啟用 Bot_B）。
17. **`gen_config.sh` usage 不完整**：兩個版本都列 arenax、sinopac。
18. **pytest marker 沒人用**：`tests/conftest.py` 依目錄自動加 `unit`／`integration`。
19. **CJEdit 與 README 不符**：broker 預設 arenax，印出的指令改成 `<目前的 python> <檔案>`，README 已改寫；產生的檔案只有選 sinopac 時才需要四個憑證。
20. **`arenaxd --host` 可綁到 loopback 以外**：非 loopback 位址直接拒絕；`system --host` 已隨 `system` 刪除。
21. **CJNews 只有 CNYES 能用**：選項剩 CNYES 與 NewsAPI，NewsAPI 會帶 `NEWSAPI_API_KEY`，缺 key 時明確結束。
22. **`price_db_report.py` 不讀 `AX_PRICE_DB_PATH`**：預設改讀它。
23. **`windows.sh` 只能在 macOS 跑**：日期運算改用 python3。
24. **`main` 與 `cjtrade` 重複**：`main` 移除，`cjtrade` 現在是交易引擎，shell 改名 `cjshell`。

另外：shioaji 的 log 改寫到 `<logs>/shioaji.log`（`SJ_LOG_PATH`），不再在每個工作目錄留 `shioaji.log`。

另外，第二輪檢查找到並已修正：

- FinHub 沿用已在 port 上的 ArenaX 時，若它的後端（`/health` 的 `backend`）不是這次選的 mode，直接拒絕，不再把 paper run 跑在 backtest 後端上。
- `poc/backtest.sh` 的 `strategy_params.py` 也依腳本位置尋找，並不再 `unset AX_LAUNCH_MODE`。
- `load_cjsys` 的 key 清單拿掉 `AX_AUTO_TIME_PROGRESS`、`AX_AUTO_START_BACKEND`。
- 狀態 API 與 FinHub 的說明改成實際行為（有 token 時讀取也要 token；唯一的寫入是停 bot）；`config.py` 說明 host 是 FinHub 連去的位址，不是它 bind 的位址。
- shell 測試腳本的說明與 `--help` 只列實際支援的 broker；`run_broker_stability_tests.sh` 不再寫出沒人讀的帳戶檔。
- `python -m cjtrade.pkgs.ui` 接受欄位旗標（`parse_known_args`）。
- `cjshell -B arenax_legacy` 缺永豐憑證時先提示並結束。
- `scripts/quick_imports.py` 預設連永豐模擬環境（`SIMULATION=n` 才連正式帳戶）。
- CI 的 ArenaX shell job 不再跑 `gen_config.sh arenax`。

## 仍待處理

1. **FinHub 起的 backtest 伺服器預設要登入永豐。** 這是 `arenaxd --backend=backtest` 本身的預設資料來源（`sinopac,yfinance`），FinHub 與 `poc/backtest.sh` 沿用它。不想登入時設 `AX_DATA_SOURCES=finmind,yfinance`，或離線用 `AX_DATA_SOURCES=offline AX_PRICE_DB_PATH=<檔案>`。
2. **沿用已在跑的伺服器時，這次的 fund 與天數不會生效。** 伺服器的現金與預載範圍在它啟動時決定；FinHub 的 Runs 頁面顯示引擎實際拿到的餘額。要套用新的值，先停掉該伺服器。
3. **FinHub 與 `mkdocs serve` 都預設 8000。** 同時開時，其中一個要換 port（`uv run finhub --port 8010`）。
4. **CJEdit 的 `project_type` 欄位沒有作用；backend 選 `--` 時產生的檔案沒有建立 client。**

未驗證範圍：沒有執行任何會啟動伺服器、登入券商、下單或等待輸入的程式。只跑過 `arenaxd`、`aresh`、`backtest`、`finhub`、`cjshell` 的 `--help`（`finhub --help` 載入設定時會建立 `<data>/finhub/run_logs/` 並印出 SECRET_KEY 警告），以及 `check_readme_examples.py --no-smoke`。交易引擎、FinHub 的 run 流程、表單 TOML、互動 shell、CJEdit/CJNews 與 `poc/experiments` 腳本都只讀了程式碼。
