# CJTrade 執行方式總覽

依據 commit `12e0b25`（`feat/market-data`）的程式碼整理。所有指令都從 repo 根目錄執行。標示「（未驗證）」的項目是只讀程式碼推斷、沒有實際跑過的。

## 總表

| 指令 | 用途 | 需要券商帳號? | 預設 port |
|---|---|---|---|
| `uv run arenaxd` | ArenaX 模擬券商伺服器 | demo：否；backtest：預設要（可用 `--data` 避開）；paper/real：要 | 8801 demo / 8802 backtest / 8803 paper / 8888 real |
| `uv run aresh` | ArenaX 管理 shell | 否 | 連 8801（寫死） |
| `uv run cjtrade` / `uv run main` | 互動式交易 shell | arenax：否；sinopac：要 | 連 8801（`ARENAX_PORT`） |
| `uv run system` | CJTrade System（自動交易，會自己起 ArenaX） | backtest 模式：要（見問題 7） | ArenaX 依設定；系統 API 8899 |
| `uv run _system_direct` | 同上，但不啟動 ArenaX | 同上 | 8899 |
| `uv run backtest` | One-shot 向量化回測 | 取決於 ArenaX 伺服器 | 連 8801（`ARENAX_PORT`） |
| `uv run preload-prices` | 預先下載 K 線到價格快取 | 否（預設 finmind,yfinance） | — |
| `uv run insight` | 回測結果診斷報告 | 否 | — |
| `uv run strategy-tool` | 策略範本／檢查／API 清單（JSON） | 否 | — |
| `uv run test` | Shell 整合測試（legacy shell） | 預設 mock 壞掉；實際用 sinopac | — |
| `uv run atest` | Shell 整合測試（ArenaX） | 否 | 起 8801 |
| `uv run python poc/trading_engine/main.py` | 多 bot 交易引擎 | 取決於 8802 上的 ArenaX | 連 8802；狀態 API 8898；ZMQ 5555/5556 |
| `bash poc/backtest.sh` | 表單驅動的 one-shot 回測 | 取決於 mode | 起 8801/8802/8803；表單 9876 |
| `bash poc/backtest_full_simulation.sh` | 表單驅動的 `system` 啟動 | 是（同 `system`） | 同 `system` |
| `bash poc/StrategyEditor.sh` | zenity 策略編輯 PoC | — | 已失效（問題 14） |
| `uv run python scripts/check_readme_examples.py` | 檢查 README 範例 | 否 | smoke 模式會啟動範例 |
| `uv run python scripts/price_db_report.py` | 價格快取完整度報告 | 否 | — |
| `uv run python src/cjtrade/apps/CJEdit/main.py` | 快速策略編輯器 | 範本依選擇而定 | — |
| `uv run python src/cjtrade/apps/CJNews/main.py` | 新聞搜尋 | 否 | 表單 9876 |
| `uv run pytest` | 單元＋整合測試 | 否 | 整合測試需 8801 |
| `uv run --group docs mkdocs serve` | 本機文件站 | 否 | 8000 |

---

## 共用：路徑、設定檔與環境變數

### 資料存放位置（`src/cjtrade/pkgs/paths.py`）

以 platformdirs 決定位置。設定 `CJTRADE_HOME=/some/path` 後，所有類別改放到 `$CJTRADE_HOME/{data,config,cache,state,logs}`。

| 類別 | macOS 預設 | 內容 |
|---|---|---|
| data | `~/Library/Application Support/cjtrade` | `account_states/<uuid>.json`、`mirrors/<broker>_<user>.db`、`reports/`、`llm_report.txt` |
| config | 同上（macOS 上與 data 相同） | 使用者層級 `*.cjconf` |
| cache | `~/Library/Caches/cjtrade` | `arenax_price.db`（ArenaX 價格快取，可刪） |
| state | 同 data | `form_state/<schema 檔名>.json`（表單記住的答案） |
| logs | `~/Library/Logs/cjtrade` | `cjtrade_system.log` |
| reports | `<data>/reports` | `oneshot_*.pkl/.html`、`engine_*.pkl/.html/.equity.jsonl`、`*.insight.md/.json` |

Linux 是 `~/.local/share/cjtrade`、`~/.cache/cjtrade` 等。`arenaxd` 啟動時會印出實際路徑（`paths.describe()`），若 `./data/` 還有舊檔也會提示搬移指令。

### `.cjconf`（券商／服務憑證，`pkgs/config/config_loader.py`）

規則是「先設定者勝」（`load_dotenv(override=False)`），順序：

1. 已存在的環境變數
2. `./.env`
3. `./**/*.cjconf`（目前目錄遞迴，淺層優先、同層依字母）
4. `<config dir>/*.cjconf`

常用 key：`API_KEY`、`SECRET_KEY`、`CA_CERT_PATH`、`CA_PASSWORD`、`SIMULATION`（`y` = 永豐模擬環境）、`USERNAME`、`LLM_API_KEY`、`LLM_MODEL`、`GEMINI_API_KEY`、`NEWSAPI_API_KEY`。

產生範本（寫到目前目錄的 `<template>_system.cjconf`）：

```sh
bash scripts/gen_config.sh arenax     # API_KEY = testkey123，其他空白
bash scripts/gen_config.sh sinopac    # 需要自行填入永豐憑證
```

### 其他環境變數

| 變數 | 誰讀 | 作用 |
|---|---|---|
| `CJTRADE_HOME` | 全部 | 改變所有資料目錄 |
| `CJTRADE_OFFLINE=1` | `pkgs/marketdata` | 所有網路來源直接丟 `MarketDataUnavailable`，只用本機快取 |
| `FINMIND_TOKEN` | finmind 來源 | 選填；日線免 token，分線需贊助方案 |
| `AX_DATA_SOURCES`、`AX_PRICE_DB_PATH` 等 `AX_*` | `arenaxd` | 見 ArenaX 章節 |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | `arenaxd --backend=real` | 沒設就拒絕啟動 real 後端 |
| `ARENAX_HOST`（預設 localhost）、`ARENAX_PORT`（預設 8801） | `cjtrade` shell、`ArenaXBrokerAPI_v2`（`backtest`、exp 腳本） | 連哪個 ArenaX |
| `CJ_ENGINE_STATUS_PORT`（預設 8898） | 交易引擎 | 狀態 API port |
| `CJ_ENGINE_CONTROL_TOKEN` | 交易引擎狀態 API | 有設才開放 `POST /bots/{id}/stop`，且所有讀取也要帶 token |
| `CJSYS_*` | `system`、`_system_direct` | 見 `system` 章節 |
| `NEWS_SOURCE`（預設 cnyes）、`NEWSAPI_API_KEY` | `cjtrade` shell | 新聞來源 |
| `AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_DEPLOYMENT`、`AZURE_OPENAI_MODEL_NAME`、`CHATPDF_APIKEY`、`CHATPDF_BASIC_SOURCE_FILE`、`GEMINI_API_KEY` | `cjtrade` 的 `llm`、`system` | LLM 用 |
| `NTFY_SH_ENABLE=y`、`NTFY_SH_TOPIC`（預設 CJTrade）、`NTFY_SH_SERVER`（預設 https://ntfy.sh） | `system` | 下單時推播到 ntfy |
| `ALLOW_LEGACY_BROKER=y` | `cjtrade` shell | 允許 `mock`／`realistic`（但這兩個已壞，見問題 1） |
| `CJ_CHECK_NO_SMOKE=1` | README 檢查器 | 只做靜態檢查 |

---

## `arenaxd`：ArenaX 模擬券商伺服器

入口：`cjtrade.apps.ArenaX.brokerside_server:main`。本機 HTTP 伺服器，提供行情、撮合、帳戶。Swagger UI 在 `/docs`，OpenAPI 在 `/openapi.json`。

### 選項

| 選項 | 預設 | 說明 |
|---|---|---|
| `--backend {backtest,paper,demo,real}` | `demo` | 後端模式，決定載入哪個 `configs/<mode>.cjsys` |
| `--host HOST` | cjsys 的 `AX_HOST_ADDRESS`，再退回 `127.0.0.1` | 綁定位址。API 沒有逐路由認證，不要綁到 loopback 以外 |
| `--port PORT` | cjsys 的 `AX_HOST_PORT`，再退回 8801 | |
| `--data SOURCES` | `AX_DATA_SOURCES`，再退回該模式預設 | 價格來源，依序嘗試：`sinopac`、`finmind`、`yfinance`、`cache`、`offline` |
| `--price-db FILE` | `AX_PRICE_DB_PATH`，再退回 `<cache>/arenax_price.db` | SQLite 價格快取 |

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
| `AX_LAUNCH_MODE` | demo / backtest / paper / real | 讀入但程式中沒用到（問題 10） |
| `AX_REAL_ACCOUNT_BROKER_TYPE` | 空 / sinopac / sinopac / sinopac | 同上 |
| `AX_BACKTEST_DURATION_DAYS` | 11 / 300 / — / — | 回測天數（程式預設 365） |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 / 30000 / — / — | 播放倍速（程式預設 1.0） |
| `AX_HOST_ADDRESS` | 127.0.0.1 | |
| `AX_HOST_PORT` | 8801 / 8802 / 8803 / 8888 | |
| `AX_STATE_FILE` | 預設註解掉 | 要「接續」的帳戶快照；不設就是全新帳戶。每次執行都另存 `<data>/account_states/<uuid>.json` |
| `AX_SKIP_NON_TRADING_HOURS` | y / y / n / n | 自動跳過盤後與週末 |
| `AX_SKIP_DATA_PRELOAD` | n | 有解析問題（問題 9） |
| `AX_AUTO_TIME_PROGRESS`、`AX_AUTO_START_BACKEND` | y | 讀入但沒用到（問題 10） |
| `AX_COMMISSION_DISCOUNT` | 註解（1.0） | 手續費折扣，最低 NT$20 |
| `AX_SLIPPAGE_MODEL` | 註解（none） | `none`、`fixed_pct`、`fixed_tick` |
| `AX_SLIPPAGE_PCT` | 註解（0.0005） | 只用於 `fixed_pct` |
| `AX_DATA_SOURCES` | 未列在檔案中 | 同 `--data` |
| `AX_PRICE_DB_PATH` | 未列在檔案中 | 同 `--price-db` |

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
I_UNDERSTAND_REAL_TRADING_RISKS=y uv run arenaxd --backend=real
```

---

## `aresh`：ArenaX 管理 shell

入口：`cjtrade.apps.ArenaX.brokerside_server_admin_shell:main`。沒有任何選項，固定連 `localhost:8801`（`ArenaXMiddleWare()` 預設值，不讀 `ARENAX_PORT`）。不帶參數進互動模式；帶參數則執行一個指令後離開。

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
uv run aresh set-time 2025-09-01
```

---

## `cjtrade`（與 `main`）：互動式交易 shell

入口：`cjtrade:cli` → `apps/cjtrade_shell/cjtrade_shell.py:main`。`main` 是同一個函式的別名。

### 啟動

- 必要選項 `-B/--broker`。
- 啟動時一定讀 `API_KEY`、`SECRET_KEY`、`CA_CERT_PATH`、`CA_PASSWORD` 環境變數（缺任何一個就 KeyError），用 arenax 也一樣。先執行 `bash scripts/gen_config.sh arenax` 產生 `.cjconf`。
- 不會自己啟動 ArenaX，要先跑 `uv run arenaxd`。連線位址取 `ARENAX_HOST`（localhost）與 `ARENAX_PORT`（8801）。

| `--broker` | 行為 |
|---|---|
| `arenax` | 連 ArenaX，`api_key` 固定 `testkey123` |
| `sinopac` | 永豐；`SIMULATION=y` 進模擬環境；mirror DB 在 `<data>/mirrors/sinopac_<USERNAME>.db` |
| `arenax_legacy` | ArenaX ＋ 永豐真實帳戶，需要永豐憑證 |
| `mock`、`realistic` | 需 `ALLOW_LEGACY_BROKER=y`，但模組已不存在（問題 1） |
| `cathay`、`ibkr`、`mega` | 印「coming soon」後離開 |

帶 `-B` 之外的參數時執行單一指令（非互動）：`uv run cjtrade -B arenax lspos`。

### 指令

| 指令 | 說明 |
|---|---|
| `help [command]` | 列出指令或單一指令說明 |
| `date [year\|YYYY-MM-DD]` | 顯示目前（模擬）時間與月曆；`+N`/`-N` 調時間尚未實作，會印錯誤 |
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
| `info` | 顯示連線券商與新聞來源 |
| `exit` | 離開 |

```sh
uv run arenaxd &
uv run cjtrade --broker=arenax
uv run cjtrade -B arenax ohlcv 2330 0050
```

---

## `system`：CJTrade System 啟動器

入口：`cjtrade.apps.cjtrade_system.system_launcher:main`。README 說它在回測用途上已被交易引擎取代。

流程：讀 `apps/cjtrade_system/configs/<broker>_<mode>.cjsys`，broker 是 arenax 時先用 `lsof` 找出佔用該 port 的程序並 SIGKILL，在同一程序內起 ArenaX 伺服器、等 `/health`，然後執行交易系統。

### 選項

| 選項 | 預設 | 說明 |
|---|---|---|
| `-B/--broker {arenax,sinopac}` | `arenax` | |
| `-m/--mode {backtest,paper,demo,real}` | `backtest` | |
| `--host` | `CJSYS_REMOTE_HOST`，再退回 127.0.0.1 | ArenaX 位址 |
| `--port` | `CJSYS_REMOTE_PORT`，再退回 8801 | ArenaX port |
| `--dry-run` | — | 印出解析後的 SystemConfig JSON 後離開 |

存在的設定檔：`arenax_backtest`（ArenaX 8802）、`arenax_demo`（8801）、`arenax_paper`（8803）、`sinopac_real`。其他組合會直接 exit 1。

### `CJSYS_*` key（環境變數優先於檔案）

| Key | 程式預設 | 說明 |
|---|---|---|
| `CJSYS_WATCH_LIST` | 空（改看現有部位） | 逗號分隔 |
| `CJSYS_REMOTE_HOST` / `CJSYS_REMOTE_PORT` | localhost / 8801 | |
| `CJSYS_BACKTEST_DURATION_DAYS` | backtest/demo 7，其他無限 | |
| `CJSYS_BACKTEST_PLAYBACK_SPEED` | — | 傳給 ArenaX（paper/real 強制 1.0） |
| `CJSYS_BACKTEST_START_DATE` | 空 = 隨機 | `YYYY-MM-DD` |
| `CJSYS_SKIP_NON_TRADING_HOURS` | — | paper/real 強制關閉 |
| `CJSYS_STATE_FILE` | — | 傳給 ArenaX 當接續快照（見問題 8） |
| `CJSYS_ANALYSIS_INTERVAL` | 30 | 模擬秒 |
| `CJSYS_CHECK_FILL_INTERVAL` | 60 | |
| `CJSYS_DISPLAY_TIME_INTERVAL` | 40 | |
| `CJSYS_LLM_REPORT_INTERVAL` | 300 | |
| `CJSYS_PRICE_MONITOR_INTERVAL` | 60 | |
| `CJSYS_BB_MIN_WIDTH_PCT` | 0.01 | |
| `CJSYS_BB_WINDOW_SIZE` | 20 | |
| `CJSYS_RISK_MAX_POSITION_PCT` | 0.05 | |
| `CJSYS_API_HOST` / `CJSYS_API_PORT` | 127.0.0.1 / 8899 | 系統 API |
| `CJSYS_API_ALLOWED_ORIGINS` | localhost/127.0.0.1 的 3000、5173、8080 | 逗號分隔；`none` 關閉 CORS |

### 系統 API（port 8899，aiohttp，無認證）

`POST /api/v1/auth/login`、`GET /api/v1/account`、`GET /api/v1/positions`、`GET /api/v1/trades`、`GET /api/v1/equity_curve`。

輸出：log 在 `<logs>/cjtrade_system.log`，LLM 報告在 `<data>/llm_report.txt`，mirror DB 在 `<data>/mirrors/`。

```sh
uv run system --dry-run -m demo
uv run system --broker=arenax --mode=demo
CJSYS_WATCH_LIST=2330,2317 uv run system -m backtest
```

## `_system_direct`

入口：`cjtrade_system_arenax:main_system`。選項只有 `-B/--broker {arenax,sinopac}`（預設 arenax）與 `-m/--mode`（預設 backtest）。不啟動 ArenaX，直接連 `CJSYS_REMOTE_HOST:CJSYS_REMOTE_PORT`，適合 ArenaX 已經自己跑起來的情況。

```sh
uv run arenaxd --backend=demo &
uv run _system_direct -m demo
```

---

## `backtest`：One-shot 回測

入口：`cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest:main`。一次從 ArenaX 取全部 K 線，在記憶體跑策略。需要 ArenaX 在 `ARENAX_PORT`（預設 8801）上運作；如果 ArenaX 用 backtest 模式（8802），要設 `ARENAX_PORT=8802`。

| 選項 | 預設 | 說明 |
|---|---|---|
| `--symbol` | 無（實際必填，沒給會丟 ValueError） | 例 `2330` 或 `2330,0050` |
| `--start` | 隨機（今天往前 duration+7 到 10 年之間） | `YYYY-MM-DD` |
| `--duration` | 365 | 日曆天 |
| `--interval {1m,5m,1h,1d}` | `1d` | |
| `--balance` | 1000000 | |
| `--strategy` | `BollingerStrategy` | 另有 `SupportResistanceStrategy`、`DCA_Monthly`、`DonchianBreakoutStrategy`、`ADXAdaptiveStrategy`、`BaselineStrategy` |
| `--params` | — | `'bb__window_size:30,risk__max_position_pct:0.1'` |
| `--show-params` | — | 印參數設定後離開 |
| `--compare` | — | 六種策略一起跑並輸出比較 |
| `--no-browser` | — | 不開瀏覽器 |

輸出：`<reports>/oneshot_<label>_<sid8>.pkl` 與 `.html`，最後印 `insight <sid8>`。`--compare` 的 HTML 寫在目前目錄（問題 11）。

```sh
uv run arenaxd &
uv run backtest --symbol 2330 --start 2024-01-01 --duration 180 --no-browser
uv run backtest --show-params --interval 1d
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

入口：`cjtrade.apps.strategy_tool:main`。輸出一律是一個 JSON 物件；只要問題有被回答就 exit 0（包括「策略有錯」）。

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

## 交易引擎：`poc/trading_engine/main.py`

一個 master 程序持有券商連線與 RiskGate，每根 1m K 棒透過 ZMQ（PUB `tcp://127.0.0.1:5555`、PULL `tcp://127.0.0.1:5556`）發給各 bot 子程序；bot 回傳 OrderIntent，master 決定是否下單。

### 前置

引擎不會啟動 ArenaX，並固定連 `localhost:8802`（`ARENAX_PORT = 8802` 寫在程式裡，不讀環境變數）。先起 backtest 模式的伺服器：

```sh
uv run arenaxd --backend=backtest --data=finmind,yfinance > /dev/null 2>&1 &
sleep 15
uv run python poc/trading_engine/main.py \
  --broker=arenax --mode=backtest --watch-list=2357 \
  --fund=1000000 --days=30 --start-date=2025-09-01 --speed=0
```

### 參數（共用表單 `poc/backtest_full_simulation.toml`，CLI renderer）

FormEngine 掃描 `sys.argv`，接受 `--flag value`、`--flag=value`。命令列有給的欄位不再詢問，其餘會在終端機提問（預設值來自 `<state>/form_state/backtest_full_simulation.json` 記住的答案）。要完全不互動就七個都給。

| `cli_arg` | 欄位 | 預設 | 引擎實際用途 |
|---|---|---|---|
| `--broker` | broker（arenax、sinopac） | arenax | 只記錄在 log，實際永遠連 ArenaX（問題 16） |
| `--mode` | mode（backtest、paper、demo） | backtest | paper 改用 realtime 時鐘；不改連線 port |
| `--speed` | playback_speed（0、0.5 … 30000） | 1200 | 回放倍速；`0` = 全速 |
| `--watch-list` | watch_list | 記住的值 | 逗號分隔；空的話引擎直接結束 |
| `--fund` | fund | 500000 | 只跟券商餘額比較並警告，不會設定餘額 |
| `--days` | days | 365 | 回放天數，區間 `[start, start+days)` |
| `--start-date` | start_date（選填） | 空 = 用伺服器的時間軸起點 | |

另外一個不經過表單的旗標：`--roster=PATH`（必須是 `=` 形式）。

### `--roster` 格式

JSON 陣列，每個元素：

```json
[{"bot_id": "Bot_U1", "script": "bot_custom.py", "symbol": "2317",
  "extra": ["/path/to/strategy.py"]}]
```

`bot_id` 不可重複；`script` 必須是 `poc/trading_engine/` 下的 `bot_*.py`；`symbol` 不在 watch list 的 bot 不會啟動；檔案有問題時整個 run 直接中止，不會改用預設名單。沒給 `--roster` 時用程式內的 `BOT_ROSTER`（目前只啟用 `Bot_B`，2357）。

### CLOCK 模式

模組常數 `CLOCK`（預設 `"replay"`），要改就編輯檔案。`--mode` 是 paper 或 real 時一律改用 realtime。

| 值 | 行為 |
|---|---|
| `replay` | 以 `GET /api/v1/clock/timeline` 的時間戳為唯一時間來源，引擎每步用 `PATCH /api/v1/clock` 推進；同資料兩次執行結果相同 |
| `scaled` | ArenaX 自己跑時鐘，引擎依伺服器 `playback_speed` 取樣 |
| `realtime` | 60 秒市場時間 = 60 秒真實時間，不碰券商控制面 |

其他寫在檔案裡的常數：`RISK_MAX_ORDERS_PER_BAR=3`、`RISK_MAX_LOSS_PCT=0.25`、`RISK_DUPLICATE_WINDOW_BARS=3`、`ACCOUNT_READ_MAX_FAILURES=5`、`BOT_SILENT_BARS=20`、`BOT_HANDSHAKE_TIMEOUT_S=30`、`BAR_BARRIER_TIMEOUT_S=30`。每個 bot 分到的資金 = 券商餘額 ÷ 實際啟動的 bot 數。

### 狀態 API（`status_api.py`，固定 127.0.0.1，port `CJ_ENGINE_STATUS_PORT` 或 8898）

會檢查 Host header，不送 CORS header。有設 `CJ_ENGINE_CONTROL_TOKEN` 時，所有路由都要 `Authorization: Bearer <token>`。

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

bot 由 master 以 `python -u bot_x.py <bot_id> <balance> <session_id> <symbol> [extra...]` 啟動，連續 180 秒沒收到資料會自行結束。

### 跑自訂策略

1. 用 `cjtrade.pkgs.strategy.authoring` 寫一個檔案：定義 `on_bar(bar, account)`，回傳 `buy()`、`sell()` 或 `hold()`；`init`、`on_fill`、`on_end` 選填；參數用 `param.int(...)`、`param.float(...)`，指標用 `ta.*`。
2. 檢查：`uv run strategy-tool check --file my_strategy.py`。
3. 寫 roster 並執行：

```sh
uv run strategy-tool template --kind bb      # 起手範本（JSON 的 source 欄位）
cat > /tmp/roster.json <<'EOF'
[{"bot_id": "Bot_U1", "script": "bot_custom.py", "symbol": "2317", "extra": ["/abs/path/my_strategy.py"]}]
EOF
uv run python poc/trading_engine/main.py --roster=/tmp/roster.json \
  --broker=arenax --mode=backtest --watch-list=2317 --fund=1000000 \
  --days=30 --start-date=2025-09-01 --speed=0
```

### 輸出

`<reports>/engine_<sid8>.equity.jsonl`（執行中寫入）、`engine_<sid8>.pkl`、`engine_<sid8>.html`。之後用 `uv run insight` 分析。

`poc/trading_engine/README.md` 另有一段會先 `kill -9` 佔用 8802 的 python 程序、再起 `AX_BACKTEST_PLAYBACK_SPEED=60.0 uv run arenaxd --backend=backtest` 的腳本。

---

## `poc/` 下的 shell 腳本

### `poc/backtest.sh`：表單驅動的 one-shot 回測

1. 用 FormEngine 跑 `poc/backtest.toml`，再用 `poc/strategy_params.py` 問該策略的參數。
2. 依 mode 設 `ARENAX_PORT`（backtest 8802、paper 8803、其他 8801），伺服器沒在跑就 `uv run arenaxd --backend=$ARENAX_MODE`（結束時關掉）。
3. 執行 `cjtrade_oneshot_backtest`。

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

需要 `curl` 與 `jq`。

```sh
bash poc/backtest.sh --renderer=cli
bash poc/backtest.sh --renderer=cli --watch-list 2330 --fund 1000000 --start 2024-01-01 \
  --days 180 --interval 1d --mode demo --strategy BollingerStrategy
```

### `poc/backtest_full_simulation.sh`：表單驅動的 `system`

用 `python -m cjtrade.pkgs.ui poc/backtest_full_simulation.toml --renderer=cli` 問 broker、mode、speed、watch list、fund、days、start date，產生 `arenax_CJ.json` 初始帳戶（paper/real 除外），設 `USERNAME=CJ`、`CJSYS_STATE_FILE=arenax_CJ.json` 後執行 `uv run system`。Linux 上會開 `gnome-terminal` 監看；macOS 或設 `SKIP_DISPLAY` 時只印 stub。

目前只能不帶參數執行（全部在終端機回答），帶任何欄位旗標都會失敗（問題 12）。需要 `jq`，且目前目錄要有 `./data/`（問題 13）。

```sh
bash poc/backtest_full_simulation.sh
```

### `poc/StrategyEditor.sh`

zenity 選檔與編輯視窗的 PoC，產生 `./data/<ts>_strategy.cj` 並執行。目前已失效（問題 14）。

---

## `scripts/`

| 腳本 | 用法 | 說明 |
|---|---|---|
| `gen_config.sh` / `gen_config.bat` | `bash scripts/gen_config.sh {arenax\|sinopac\|mock}` | 在目前目錄產生 `<template>_system.cjconf`；檔案已存在時會互動詢問是否覆蓋 |
| `gen_init_account.sh` / `.bat` | `bash scripts/gen_init_account.sh <broker> [balance]` | 產生 `<broker>_<USERNAME>.json` 帳戶快照（balance 預設 10000）；需要 `jq` |
| `gen_todos_report.sh` | `bash scripts/gen_todos_report.sh` | 用 `git grep TODO` 產生 `todos_report_for_<tag 或 commit>.md` 到 repo 根目錄 |
| `check_readme_examples.py` | 見下方 | README 範例檢查 |
| `price_db_report.py` | 見下方 | 價格快取報告 |
| `quick_imports.py` | （REPL 匯入捷徑） | 已失效（問題 1） |

### `scripts/check_readme_examples.py`

檢查清單中的 README（`README.md`、`src/cjtrade/README.md`、`src/cjtrade/apps/README.md` 與 ArenaX、CJEdit、CJNews、cjtrade_shell、cjtrade_system、`pkgs/brokers` 的 README）。每個 code block 前一行都要有標記，沒標記就算錯：

- `<!-- cjcheck: smoke -->`、`<!-- cjcheck: smoke timeout=20 -->`：啟動，不可在一開始就死掉（逾時仍在跑算通過）
- `<!-- cjcheck: run -->`：必須 exit 0
- `<!-- cjcheck: static -->`：不啟動，只檢查 `uv run NAME` 存在且目標函式存在、路徑存在、`--flag` 被接受、已知 port 的 URL 路由存在、python block 可解析
- `<!-- cjcheck: skip reason="..." -->`：排除

| 選項 | 說明 |
|---|---|
| `--no-smoke` | 只做靜態檢查（等同 `CJ_CHECK_NO_SMOKE=1`），不到一秒、不需網路 |
| `--list` | 列出每個 block 與檢查方式 |

本次快照執行 `--no-smoke` 結果：38 個 block，36 檢查、2 skip，全部通過。

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
| `--db` | `<cache>/arenax_price.db` | 不讀 `AX_PRICE_DB_PATH` |

```sh
uv run python scripts/price_db_report.py
uv run python scripts/price_db_report.py -s 2317 --months --days
uv run python scripts/price_db_report.py --db exp.db
```

---

## 開發流程

### 測試

`pyproject.toml` 設定 `testpaths = ["tests/unit", "tests/integration"]`、`addopts = "-v --tb=short"`。`tests/manual/` 不會被收集（需要真券商）。宣告了 `unit`、`integration` 兩個 marker，但沒有測試使用它們。整合測試在 `127.0.0.1:8801` 沒有服務時會自動 skip。

```sh
uv run pytest                                       # unit + integration
uv run pytest tests/unit/ --cov=src/cjtrade --cov-report=term-missing
bash tests/run_broker_stability_tests.sh --broker=arenax --coverage
```

| 指令 | 說明 |
|---|---|
| `bash tests/run_broker_stability_tests.sh [--broker=arenax] [--coverage]` | 在 repo 根目錄覆寫 `backtest_account_state.json` 與 `demo_account_state.json`，必要時起 `uv run arenaxd`（demo），跑 `tests/integration/<broker>`；輸出 `LAST_BROKER_STABILITY_TEST.log`、`htmlcov/integration_<broker>`；需要 `jq` |
| `uv run atest [選項]` | 跑 `tests/test_cjtrade_integration_arenax.sh`：必要時起 arenaxd，再逐一執行 `cjtrade_shell.py --broker=arenax` 指令 |
| `uv run test [選項]` | 跑 `tests/test_cjtrade_integration.sh`，對象是 `cjtrade_shell_legacy.py`；預設 broker 是 `mock`（已壞），實際用法是 `--broker=sinopac` |
| `bash tests/find_bad_commit.sh --good <sha> --bad <sha> --script <cmd>` | `git bisect run` 包裝；缺參數會互動詢問 |

`test`／`atest` 選項：`--broker=<name>`、`--group={trading,query,market,system,news,all}`（預設 all）、`--continue-on-error`、`--no-log`、`-h`。log 寫到 `LAST_CJTRADE_INTEGRATION_TEST.log`。

`tests/manual/` 與 `src/cjtrade/apps/ArenaX/tests/`（`test_server_time.sh`、`price_downloader.py`）是手動腳本，需要真券商或會自己起伺服器，不在 CI 中。

### pre-commit（`.pre-commit-config.yaml`）

安裝：`uv run pre-commit install`。本地 hook 都是 `pass_filenames: false`，所以每次 commit 都會完整執行。

| Hook id | 執行內容 |
|---|---|
| `trailing-whitespace`、`end-of-file-fixer`、`check-yaml` | pre-commit-hooks v4.6.0 |
| `reorder-python-imports` | v3.16.0 |
| `readme-examples` | `uv run python scripts/check_readme_examples.py`（smoke 模式會啟動範例，需網路） |
| `unit-tests` | `uv run pytest tests/unit/ --tb=short -q --cov=src/cjtrade --cov-report=term-missing --cov-report=html:htmlcov/unit` |
| `ArenaX-broker-integration-test` | `bash tests/run_broker_stability_tests.sh --broker=arenax --coverage`（會起 arenaxd，yfinance 需網路） |
| `arenax-shell` | `uv run atest --broker=arenax --group=all` |
| `sinopac-shell` | `uv run test --broker=sinopac --group=all`（會登入永豐） |

跳過特定 hook 用 `SKIP`（逗號分隔 hook id）：

```sh
SKIP=sinopac-shell git commit -m "..."
SKIP=sinopac-shell,arenax-shell,ArenaX-broker-integration-test git commit -m "..."
CJ_CHECK_NO_SMOKE=1 SKIP=sinopac-shell git commit -m "..."
```

### 文件

`mkdocs.yml` 的 `docs_dir` 是 `doc/`，`strict: true`。英文頁是 `name.md`，繁中頁是 `name.zh-TW.md`。

```sh
uv run --group docs mkdocs serve                  # http://127.0.0.1:8000
uv run --group docs mkdocs build --strict --site-dir site
```

### CI（`.github/workflows/`）

| Workflow | 觸發 | 內容 |
|---|---|---|
| `ci.yml` | push、pull_request、手動 | 各 hook 一個 job：`file-hooks`（只對本次變更檔案跑 whitespace/EOF/YAML/import order）、`readme-examples`、`unit-tests`（上傳 `htmlcov/unit`）、`arenax-integration`、`arenax-shell`（先 `gen_config.sh arenax`）、`sinopac-shell`（需 `SINOPAC_API_KEY`、`SINOPAC_SECRET_KEY`、`SINOPAC_CA_CERT_BASE64`、`SINOPAC_CA_PASSWORD` secrets，缺就跳過；強制 `SIMULATION=y`；fork 的 PR 不跑）。全部 `TZ=Asia/Taipei`、Python 3.12、`UV_LOCKED=1` |
| `codeql.yml` | 對主分支的 push/PR、每週一 03:17（台北）、手動 | CodeQL `security-extended`，語言 python 與 actions；忽略 `exp`、`ref`、`tests` |
| `docs.yml` | push、pull_request、手動 | `uv sync --locked --only-group docs` 後 `mkdocs build --strict`；只有主分支的 push 會部署到 GitHub Pages |

---

## 小型 app

### CJEdit

```sh
uv run python src/cjtrade/apps/CJEdit/main.py
```

在終端機用表單（`pages/index.toml`，CLI renderer）問：編輯器（gedit、nano、vim、vscode、sublime，預設 vscode）、broker（預設 sinopac）、ArenaX backend（`--`、demo、backtest、paper）。之後把對應的 import 範本寫進暫存檔 `/tmp/.../cjedit_*.py`，用選定的編輯器開啟，最後印出執行該檔的指令。範本啟動時會讀 `API_KEY` 等四個環境變數。沒有命令列選項。

### CJNews

```sh
uv run python src/cjtrade/apps/CJNews/main.py
```

用 web 表單（127.0.0.1:9876，會開瀏覽器）問關鍵字（預設 台積電）、來源（CNYES 鉅亨網、NewsAPI、財報狗）、筆數（1 到 20，預設 5），結果也用 web 表單顯示。關鍵字沒結果時改抓頭條。只有 CNYES 能用（問題 21）。沒有命令列選項。

### `python -m cjtrade.pkgs.ui`

```sh
uv run python -m cjtrade.pkgs.ui poc/backtest.toml --renderer=cli
```

通用表單執行器：位置參數是 TOML，`--renderer`（預設 `auto`：有 zenity 用 zenity，否則 cli），輸出 `export VAR='...'` 供 `eval`。不接受欄位旗標（問題 12）。

### `poc/experiments/bin/`（研究用腳本）

| 腳本 | 用法 |
|---|---|
| `run.sh` | `./poc/experiments/bin/run.sh <tag> <symbol> <strategy> <interval> <start> <duration> [params]`；環境 `BAL`（1000000）、`ARENAX_PORT`（8802）、`EXPECT_BARS`；跑回測＋insight，追加到 `poc/experiments/runs.csv` |
| `custom_backtest.py` | `--file`（必填）、`--class`、`--symbol`（必填）、`--start`（必填）、`--duration`（必填）、`--interval`（1m）、`--balance`、`--params`；用自寫的 BaseStrategy 跑 one-shot |
| `prewarm.sh` | `./poc/experiments/bin/prewarm.sh <tf> <symbol...>`；環境 `ARENAX_PORT`（8802）、`PREWARM_SLEEP`（2）；逐年預熱價格快取 |
| `prewarm_one.py` | `python poc/experiments/bin/prewarm_one.py <sym> <tf> <start> <end>` |
| `report.sh` | `./poc/experiments/bin/report.sh [tag\|--pass\|--bad]`，讀 `poc/experiments/runs.csv` |
| `windows.sh` | `./poc/experiments/bin/windows.sh {is,oos,is-seg,oos-seg,stress-seg}`，印預先登記的評估視窗；只能在 macOS 上跑（BSD `date`） |

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

### 離線實驗

```sh
uv run preload-prices --price-db exp.db --symbols 2317 --start 2025-09-01 --end 2025-10-01
uv run python scripts/price_db_report.py --db exp.db -s 2317
CJTRADE_OFFLINE=1 uv run arenaxd --backend=backtest --data=offline --price-db=exp.db &
```

要完全和預設資料隔離，再加上 `CJTRADE_HOME=/tmp/cj-exp`。

### 跑 trading engine 回測

```sh
uv run arenaxd --backend=backtest --data=finmind,yfinance > /dev/null 2>&1 &
sleep 15
uv run python poc/trading_engine/main.py --broker=arenax --mode=backtest \
  --watch-list=2357 --fund=1000000 --days=30 --start-date=2025-09-01 --speed=0
curl -s http://127.0.0.1:8898/status      # 執行中另開終端機查看
```

watch list 必須包含 roster 裡 bot 的 symbol（預設 Bot_B 是 2357）。

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
SKIP=sinopac-shell git commit -m "..."
```

沒有永豐憑證時一定要 `SKIP=sinopac-shell`。離線時再加 `arenax-shell,ArenaX-broker-integration-test` 與 `CJ_CHECK_NO_SMOKE=1`。

---

## 發現的問題

1. **legacy mock broker 已不存在，多個入口因此失效。** `AccountClient(BrokerType.MOCK)` 會 import `cjtrade.pkgs.brokers.arenax.legacy.mock_broker_api`，該模組已不存在。受影響：`cjtrade -B mock`、`cjtrade -B realistic`、`uv run test`（預設 `--broker=mock`）、`scripts/quick_imports.py`（另外它的 `sys.path` 指到 repo 的上一層目錄，docstring 裡的 `from cjtrade.scripts.quick_imports import *` 也不是可匯入的模組）、`scripts/gen_config.sh mock` 產生的設定。（依程式碼推斷，未實際執行）
2. **`cjtrade` shell 啟動時一定讀四個永豐憑證環境變數。** 用 `os.environ["API_KEY"]` 等寫法，連 `--broker=arenax` 沒有 `.cjconf` 也會 KeyError。CI 用 `gen_config.sh arenax` 繞過。
3. **`info` 指令從不顯示版本。** 它檢查 `src/cjtrade/core/cjtrade_shell.py`，該檔不存在。`date +N/-N` 也只會印「尚未支援」。
4. **測試腳本開頭註解寫錯檔名。** `tests/test_cjtrade_integration*.sh` 的 Usage 寫 `./test_cjtrade_shell_all_cmds.sh`；`uv run test` 測的是 `cjtrade_shell_legacy.py`，不是目前的 shell。
5. **`aresh` 只能連 `localhost:8801`。** 沒有任何選項，也不讀 `ARENAX_PORT`，所以管不到 backtest（8802）或 paper（8803）伺服器。
6. **`system` 部分 mode 沒有設定檔。** `system -m real`（arenax）找不到 `arenax_real.cjsys`，直接 exit 1；`-B sinopac` 只有 `-m real` 可用。`configs/realistic_backtest.cjsys` 用的是沒有 `CJSYS_` 前綴的舊 key，`realistic` 也不是 `-B` 的選項，這個檔案沒有任何入口會讀。
7. **`system` 不讀 ArenaX 的 `AX_*` 設定。** 啟動器沒有呼叫 `load_cjsys()`，所以 `ArenaX/configs/*.cjsys` 與 `AX_*` 環境變數（成本模型、`AX_DATA_SOURCES`、`AX_PRICE_DB_PATH` 等）都不會生效，也沒有 `--data` 選項。結果是 `system -m backtest` 一定用 `sinopac,yfinance`，需要永豐登入。另外它會對設定的 port 上任何程序送 SIGKILL。
8. **`system` 的設定檔固定指定 `CJSYS_STATE_FILE`。** `arenax_*.cjsys` 寫了 `CJSYS_STATE_FILE = backtest_account_state.json` 等，會傳給 ArenaX 當「接續快照」。這正是 ArenaX cjsys 註解警告的行為（每次都從上次結束處開始）。檔案不存在時的行為未驗證。
9. **`AX_SKIP_DATA_PRELOAD = n` 會被當成 true。** `load_cjsys` 沒有把這個值轉成 bool，字串 `"n"` 直接傳進 backend，`not self.skip_data_preload` 因此是 False。已用 `load_cjsys("demo")` 驗證解析出 `'n'` 且 `bool('n') is True`；推斷的影響是同步既有部位時不會預載歷史資料與更新部位價格。
10. **有些 `AX_*` key 讀了但沒用到。** `AX_LAUNCH_MODE`、`AX_REAL_ACCOUNT_BROKER_TYPE`、`AX_AUTO_TIME_PROGRESS`、`AX_AUTO_START_BACKEND` 在 ArenaX 程式碼中找不到使用處，模式完全由 `--backend` 決定。
11. **`backtest` 的 docstring 寫了沒實作的環境變數。** 列出的 `CJSYS_ONESHOT_DURATION_DAYS`、`CJSYS_ONESHOT_START`、`CJSYS_ONESHOT_END`、`CJSYS_ONESHOT_INTERVAL`、`CJSYS_ONESHOT_INITIAL_BALANCE` 程式都不讀，只能用 CLI 旗標；`--symbol` 實際上是必填，但 argparse 沒標 required。`--compare` 的 `comparison_*.html`、`fullreport_*.html` 寫在目前目錄而非 `reports_dir()`。
12. **`backtest_full_simulation.sh` 帶任何欄位旗標都會失敗。** `python -m cjtrade.pkgs.ui` 用 `parse_args()`，例如 `--mode backtest` 會得到 `unrecognized arguments`（已驗證）。因為輸出經過 `| grep '^export '` 再 `eval`，`set -e` 抓不到，腳本會在變數全空的情況下繼續（它不像 `backtest.sh` 有檢查必填變數）。
13. **`backtest_full_simulation.sh` 用舊路徑。** 它清空與監看 `./data/arenax_CJ.db` 和 `./llm_report.txt`，但 `system` 現在寫到 `<data>/mirrors/` 和 `<data>/llm_report.txt`。`./data/` 不存在時 `echo > ./data/arenax_CJ.db` 會失敗，`set -e` 讓腳本中止。表單的 mode 選項沒有 real，腳本裡卻有處理 real 的分支。
14. **`poc/StrategyEditor.sh` 已失效。** shebang 不在第一行；產生的檔案 import `cjtrade.pkgs.brokers.arenax.mock_broker_api`，該模組不存在；輸出寫在 `./data/`。
15. **`poc/backtest.sh` 把 `--start` 加了兩次。** 有兩段一樣的 `if [ -n "$START_DATE" ]`，argparse 取最後一個，所以結果沒錯，只是重複。
16. **交易引擎的部分旗標沒有實際作用。** `ARENAX_PORT = 8802` 寫死，README 範例的 `ARENAX_PORT=8802` 環境變數對 `main.py` 沒有效果；`--broker` 只寫進 log，一律連 ArenaX；`--mode paper` 只改時鐘，仍連 8802，連不到 8803 的 paper 伺服器；`--fund` 不設定帳戶餘額，只印警告。`BOT_ROSTER` 上方註解說只啟用 Bot_C，實際啟用的是 Bot_B。README 稱狀態頁為唯讀，但有 `POST /bots/{id}/stop`（需 token）。
17. **`gen_config.sh` 的 usage 訊息不完整。** 列出 `[mock, sinopac]`，但也支援 `arenax`（`.bat` 版本有列）；它的 `mock` 範本對應的 broker 已失效。
18. **pytest marker 沒有人用。** `unit`、`integration` 宣告在 `pyproject.toml`，但沒有任何測試使用。
19. **CJEdit 的 README 與實際行為不符。** README 說「在瀏覽器開啟編輯器」，實際是終端機表單加本機編輯器（vscode、vim 等）。印出的執行指令寫死 `$HOME/Downloads/gitrepo/CJTrade/.venv`。broker 預設 sinopac，產生的範本要求四個憑證環境變數。
20. **`arenaxd --host` 可以綁到 loopback 以外。** API 自己的說明寫「沒有逐路由認證，不要綁到 127.0.0.1 以外」，但 `--host`／`AX_HOST_ADDRESS` 沒有阻擋。`system` 的 `--host` 也是一樣。
21. **CJNews 只有 CNYES 能用。** 選「財報狗」會丟 `NotImplementedError`；選「NewsAPI」時 `NewsClient(provider)` 沒傳 `api_key`，`NewsAPIProvider` 要求 `api_key`，推斷會失敗（未執行）。
22. **`price_db_report.py` 不讀 `AX_PRICE_DB_PATH`。** 預設只看 `paths.price_db_path()`，用自訂快取時要加 `--db`。
23. **`poc/experiments/bin/windows.sh` 只能在 macOS 上跑。** 它用 BSD `date -j -v`，Linux 會失敗。
24. **`main` 與 `cjtrade` 重複。** 兩者指向同一個函式，`main` 沒有其他用途。

未驗證範圍：沒有執行任何會啟動伺服器、登入券商、下單或等待輸入的程式。只跑過下列指令的 `--help`：`arenaxd`、`system`、`_system_direct`、`aresh`、`cjtrade`、`backtest`、`strategy-tool`、`insight`、`preload-prices`、`check_readme_examples.py`、`price_db_report.py`；另外跑了 `check_readme_examples.py --no-smoke`、`python -m cjtrade.pkgs.ui` 的錯誤路徑，以及 `load_cjsys("demo")` 的解析。交易引擎、表單 TOML、互動 shell 與 CJEdit/CJNews 都只讀了程式碼。
