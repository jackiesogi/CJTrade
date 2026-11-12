# CJTrade 低曝險策略研究 — 實驗手冊

給要執行這個實驗的研究員（人或 agent）。**這份文件就是你的 API。** 裡面每一條指令都在這台機器上實測過，每一個數字都是實際跑出來的，不是推測。

專案根目錄 `~/Downloads/gitrepo/CJTrade`，所有指令從這裡執行。

---

## 名詞對照表

| 簡稱 | 全稱 | 意思 |
|---|---|---|
| **IS** | In-Sample（樣本內） | `2021-01-01 → 2024-12-31`。訓練資料，隨便看、隨便調參、隨便重跑 |
| **OOS** | Out-of-Sample（樣本外） | `2025-01-01 → 2026-11-11`。驗收資料，**只能碰一次** |
| **STRESS** | — | `2020-03-02 → 2020-12-31`。疫情崩盤，最後才碰 |
| **TiM** | Time in Market | 在市場內的時間比例。**這個實驗最在意的指標** |
| **CAGR** | Compound Annual Growth Rate | 年化複合報酬率 |
| **MDD** | Max Drawdown | 最大回撤（從高點跌到低點的最大幅度） |
| **Sharpe** | Sharpe ratio | 報酬 ÷ 波動，風險調整後報酬 |
| **trips** | round trips | 完整的一買一賣 |
| **bars** | — | K 線根數。1m 就是每分鐘一根 |
| **sid** | session id | 每次回測的唯一識別碼，用來查 insight 報告 |
| **seg** | segment | **不重疊**的分段（`is-seg` / `oos-seg`），彼此獨立，是獨立證據 |
| **滾動視窗** | rolling window | **重疊**的視窗（`is` / `oos`），相鄰共用 5/6 資料，看分布用 |
| **P0–P6** | — | 實驗的 7 個階段（第 7.2 節） |
| **E001** | — | 實驗日誌條目編號（`JOURNAL.md`），和 `run.sh` 的 tag 一致 |
| **O001** | — | 框架觀察編號（`OBSERVATIONS.md`） |

**為什麼要分 IS / OOS**：在 IS 上得到的好數字不算證據，因為你是看著它調出來的。調了 300 次才找到一組漂亮的，那組漂亮很可能只是配合了那段資料的特定走勢，不是真的規律。只有在**從沒影響過任何決策**的資料上測出來的結果，才是對未來的合理估計。這就是為什麼 OOS 只能碰一次：碰第二次、根據結果回去改策略，OOS 就變成第二個 IS，驗收就失效了。

---

## 0. 你要找什麼

一套**低市場曝險**的單一個股策略。核心精神：**我們的目的是降低在市場上的曝險，不是賺最多。**

### 0.1 目標（越優越好，不是過關就停）

| 指標 | 最低門檻 | 良好 | 優秀 | 從哪裡讀 |
|---|---|---|---|---|
| **Time in market** | ≤ 20% | ≤ 10% | ≤ 5% | `performance.time_in_market` |
| **Sharpe ratio** | ≥ 1.0 | ≥ 1.25 | ≥ 1.5 | `performance.sharpe` |
| **CAGR** | ≥ 5% | ≥ 8% | ≥ 12% | `performance.cagr` |
| **Max drawdown** | 比同期 0050 淺 | ≤ 10% | ≤ 6% | `performance.max_drawdown` |

最低門檻是**全部都要過**，不是達到一項就算。過了之後繼續往「良好／優秀」推進，並把整條權衡曲線回報出來（第 9 節）。

**當兩個候選策略都過最低門檻時，曝險低的優先。** TiM 12% / CAGR 6% 的策略優於 TiM 19% / CAGR 11% 的策略。

### 0.2 穩定性（這才是真正的驗收，不是上面那張表）

「策略至少能維持運行半年是賺錢的」是你的真實目標。所以：

**在 IS 期間，必須在 8 個不重疊的 182 天分段上穩定達標：**

- **≥ 6/8 分段報酬為正**
- **最差分段報酬 ≥ -5%**
- **沒有任何單一分段貢獻超過總 IS 損益的 50%**（集中度防護，見 0.4）
- 43 個滾動視窗（重疊）：**≥ 70% 為正、最差 ≥ -10%**

**在驗證集（OOS），必須在 4 個不重疊的 170 天分段上確認：**

- **≥ 3/4 分段報酬為正**
- **最差分段報酬 ≥ -10%**
- 17 個滾動視窗的完整分布要回報（不是只報平均）

**跑完 OOS 的 4 個獨立分段並通過，才算實驗完成。**

### 0.3 策略性質（硬性排除）

- **不可以是長期持有型。** DCA、定期定額、買進不賣、`BaselineStrategy` 全部不算答案，即使數字漂亮。
- 必須有實際進出：IS 全期 round trips ≥ 10。
- `flat_periods / observations > 0.5`，也就是**超過一半的交易日完全空手**。

### 0.4 為什麼集中度防護是必要的 — 實測案例

`exp/strategies/example_breakout.py` 在 IS 全期間的數字看起來不錯：

```
sharpe=0.667907  cagr=+5.89%  mdd=-16.43%  TiM=+30.00%  trips=16
```

但拆成 8 個不重疊分段之後：

| 分段起始 | Sharpe | CAGR | TiM | trips |
|---|---|---|---|---|
| 2021-01-01 | +0.50 | +3.47% | 12% | 1 |
| 2021-07-02 | -1.22 | -4.57% | 17% | 1 |
| 2021-12-31 | -0.22 | -1.27% | 30% | 2 |
| 2022-07-01 | -1.17 | -4.81% | 16% | 2 |
| 2022-12-30 | -0.69 | -4.41% | 47% | 3 |
| 2023-06-30 | +0.34 | +0.34% | 5% | 0 |
| **2023-12-29** | **+3.98** | **+104.07%** | 57% | 1 |
| 2024-06-28 | +1.13 | +8.27% | 20% | 1 |

**4 段正、4 段負，而全期間的獲利幾乎全部來自 2023-12-29 那一段。** 那不是一套能撐半年的策略，那是一次好運被平均數藏起來。

這就是為什麼全期 Sharpe 只能初篩，分段分布才是驗收。

### 0.5 不要用每段 Sharpe 當門檻

上表裡每個分段只有 0–3 筆交易。**在 1–3 筆交易上算出來的 Sharpe 是噪音**，所以：

- 分段層級只看**報酬正負**和**最差分段**
- Sharpe 只在**全期間**（IS 1461 天 / OOS 680 天）這種有足夠交易筆數的尺度上使用

### 0.6 關於「不能跟大盤差太多」

結構上，TiM < 20% 不可能在多頭市場追上 buy&hold。所以「不差太多」在這裡的操作定義是：

> **CAGR ≥ 5% 且 Sharpe ≥ 1.0 且 max drawdown 比同期 0050 淺。**

用風險調整後表現和回撤取勝，絕對報酬輸給大盤是可以接受的。每次回報候選策略都要附上同期 0050 的對照數字（第 6.5 節）。

---

## 1. 我改了原始設計的哪些地方，以及為什麼

交付前請先看這段。原始構想有四個地方會讓實驗無法產生有意義的結論。

### 1.1 訓練區間：2021–2024 確認可行，而且多出 2020 可當壓力測試

實測透過 ArenaX 可以取到 **2020-03-02 起**的 1 分鐘資料（永豐 API 的歷史起點）。我已經把 **2020-03-02 → 2026-11-11、7 檔標的的 1m 資料全部預熱進本機 DB**（約 297 萬根 bar）。

| 區間 | 日期 | 用途 |
|---|---|---|
| **IS（可任意使用）** | 2021-01-01 → 2024-12-31（1461 天） | 調參、探索、穩定性篩選 |
| **OOS（只能碰一次）** | 2025-01-01 → 2026-11-11（約 680 天） | 最終驗收，4 個獨立分段 |
| **STRESS（最後才碰）** | 2020-03-02 → 2020-12-31 | 疫情崩盤壓力測試 |

IS 包含 2022 年空頭，所以不是單向多頭，策略必須真的能處理不同環境。

### 1.2 「不指定 --start 用隨機日期當驗證」不能當主要驗證手段

程式裡 `--start` 不給時是 `today - randint(duration+7, 3650)`，也就是**過去 10 年內任一天，完全沒有排除訓練區間**。以 182 天視窗計算：

- 約 35% 的抽樣落在完全沒有資料的範圍，直接 `RuntimeError`
- 剩下的抽樣裡，約 78% 落在 **IS 區間內**，根本不是 out-of-sample
- 沒有 seed、沒有紀錄，重跑就換一個日期

最嚴重的是：**沒有次數上限的無記錄抽樣，等於允許一直抽到好結果為止。** 那不是驗證。

**改成**：主要驗證用第 2 節預先登錄的固定分段，全部跑完、全部回報。因為清單在看到任何結果之前就固定了，而且要求回報完整分布，所以結構上無法挑好的講。隨機抽樣降為第 7.5 節的輔助盲測。

### 1.3 重疊視窗不是獨立證據

17 個每月推進的 182 天視窗，相鄰兩個共用 5/6 的資料。**那不是 17 次確認。** 它的價值是顯示完整分布和最差情況（包含跨越轉折的視窗），但要講「穩定通過 3–5 個時間段」必須用**不重疊**的分段。兩種都要跑，用途不同。

### 1.4 驗收指標需要精確定義

`time_in_market` 是 quantstats 的 exposure，在**日**解析度上計算：當天權益有變動就算在市場內。意思是：

> **當日進出、隔夜空手的策略，那一天仍然整天算在市場內。** 要讓 TiM < 20%，你必須在超過 80% 的交易日裡完全沒有部位、沒有交易。

這恰好是你要的性質，而且是個明確嚴格的目標。

---

## 2. 預先登錄的視窗與分段

```bash
# 不重疊分段 —— 獨立證據，用於穩定性驗收。輸出「起始日 天數」
./exp/bin/windows.sh is-seg       # 8 段 × 182 天，2021-01-01 .. 2024-12-27
./exp/bin/windows.sh oos-seg      # 4 段 × 170 天，2025-01-01 .. 2026-11-12
./exp/bin/windows.sh stress-seg   # 1 段 × 182 天，2020-03-02 起

# 重疊滾動視窗 —— 完整分布與最差情況。輸出起始日，每個 182 天
./exp/bin/windows.sh is           # 43 個，2021-01-01 .. 2024-07-01
./exp/bin/windows.sh oos          # 17 個，2025-01-01 .. 2026-05-01
./exp/bin/windows.sh stress       #  5 個，2020-03-01 .. 2020-07-01
```

分段的跑法：

```bash
./exp/bin/windows.sh is-seg | while read s d; do
  ./exp/bin/run.sh e042 2317 exp/strategies/my_strat.py 1m "$s" "$d" 'lookback:5400,pos_pct:0.5'
done
```

**這些清單是固定的。** 改動它去迎合結果，會讓 holdout 數字失去全部意義。如果有正當理由需要別的視窗，在日誌裡寫清楚，並且**同時保留原始清單的結果**。

---

## 3. 環境

### 3.1 價格資料庫（唯一指定）

```
~/Library/Caches/cjtrade/arenax_price.db        # 405 MB，就用這個，不要換
```

- **不要設 `CJTRADE_HOME`。** 它會一起隔離掉永豐憑證（在 `~/.config/cjtrade/`），實測 broker 會直接起不來，而且價格 DB 變成空的。
- broker 執行中會有 `-wal` 檔。要自己用 sqlite 讀的話先 `cp` 到 `/tmp`。
- 預熱前的備份：`~/cjtrade_db_backups/arenax_price.db.bak.20261113_013305`

### 3.2 已預熱的資料（已完成，你不需要再抓）

7 檔標的，**1m**，2020-03-02 → 2026-11-11：

| 標的 | 名稱 | bars | 交易日 |
|---|---|---|---|
| `0050` | 元大台灣50（ETF，基準用） | 429,401 | 1,626 |
| `2317` | 鴻海 | 436,080 | 1,630 |
| `2330` | 台積電 | 434,401 | 1,631 |
| `2357` | 華碩 | 394,658 | 1,631 |
| `2412` | 中華電（低波動） | 425,884 | 1,631 |
| `2454` | 聯發科 | 420,516 | 1,631 |
| `2881` | 富邦金 | 429,649 | 1,631 |

每天約 265 根 bar（台股 09:01–13:30 共 270 分鐘），覆蓋率完整。

**已知的上游資料缺口**（不是你的問題，遇到時不用困惑）：

- `0050` 缺 2025-06-11 ~ 2025-06-17（5 個交易日，落在 OOS 第 1 分段內）
- `2317` 缺 2025-07-30（1 天）

`1d` 和 `5m` 會從這份 1m 資料即時聚合，不需另外預熱。**`1h` 回傳 0 根 bar，不要用。**

### 3.3 啟動 broker（每個工作階段開始時）

```bash
cd ~/Downloads/gitrepo/CJTrade
(unset AX_HOST_PORT AX_HOST_ADDRESS AX_LAUNCH_MODE AX_STATE_FILE; \
 nohup uv run arenaxd --backend=backtest --port=8802 > /tmp/arenaxd.log 2>&1 &)
until curl -s --max-time 3 http://127.0.0.1:8802/health | jq -e '.running==true' >/dev/null; do sleep 1; done
echo ready
```

約 8–10 秒 ready。`unset` 是必要的：預存的 `AX_*` 環境變數會蓋掉 `backtest.cjsys`（first-wins 優先序）。

**一律用 port 8802（`backtest` backend）。** `demo`（8801）只有 yfinance 資料，會拿到完全不同的 bar。

### 3.4 環境健康檢查（每次啟動 broker 後跑一次）

```bash
./exp/bin/run.sh health 2317 BollingerStrategy 1d 2021-01-01 1461 'risk__max_position_pct:0.5'
```

必須得到 **`bars=970`、`sharpe=0.213954`、`cagr=+1.59%`、`TiM=+47.00%`**。

數字不符就是環境有問題，先修再做事（見第 6.1 節）。

---

## 4. 你可以用的工具（就這些）

**這一節以外的東西都不要用。** 不要連網查價格或新聞、不要用 trading engine、不要為了找 bug 去讀框架 source code。

### 4.1 實驗工具包 `exp/bin/`（你的主要介面）

| 指令 | 用途 |
|---|---|
| `./exp/bin/run.sh <tag> <symbol> <strategy> <interval> <start> <duration> [params]` | **跑一次回測的唯一方式。**自動重試、記錄一列 CSV、產出 insight 報告 |
| `./exp/bin/report.sh [tag\|--pass\|--bad]` | 讀回 `exp/runs.csv` |
| `./exp/bin/windows.sh is\|oos\|stress\|is-seg\|oos-seg\|stress-seg` | 預先登錄的視窗與分段 |

`<strategy>` 可以是內建策略名稱，也可以是**你自己寫的 `.py` 路徑**。兩者走同一個引擎、同一份 bar、同一個成本模型，數字可以互相比較。

```bash
# 內建策略
./exp/bin/run.sh e001 2317 DonchianBreakoutStrategy 1m 2021-01-01 1461 'donchian__period:100,risk__max_position_pct:0.5'

# 你自己寫的策略
./exp/bin/run.sh e002 2317 exp/strategies/my_strat.py 1m 2021-01-01 1461 'lookback:5400,pos_pct:0.5'
```

環境變數：`BAL`（預設 1000000）、`EXPECT_BARS`（bar 數不符就把該列標成 `BAR_MISMATCH`）。

每次 run 的產出：
- `exp/runs.csv` 追加一列（31 欄，只增不改）
- `exp/runs/<tag>/<sid>.insight.md` 和 `.insight.json`

**執行時間**：內建策略 1m 全 IS 期間約 17 秒；自訂策略約 28 秒（取決於 `on_bar` 複雜度）。182 天分段約 5–8 秒。

### 4.2 底層 CLI（`run.sh` 內部呼叫，你通常不需要直接用）

```bash
# 內建策略單次回測
ARENAX_PORT=8802 uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest \
  --symbol 2317 --start 2021-01-01 --duration 1461 --interval 1m \
  --balance 1000000 --strategy DonchianBreakoutStrategy \
  --params 'donchian__period:100,risk__max_position_pct:0.5' --no-browser

# 自訂策略單次回測
ARENAX_PORT=8802 uv run python exp/bin/custom_backtest.py \
  --file exp/strategies/my_strat.py --symbol 2317 \
  --start 2021-01-01 --duration 1461 --interval 1m \
  --balance 1000000 --params 'lookback:5400,pos_pct:0.5'
```

| flag | 說明 |
|---|---|
| `--symbol` | 單檔或多檔逗號分隔 |
| `--start` | `YYYY-MM-DD`。**一定要給**，不給就是隨機日期 |
| `--duration` | **日曆天**，不是交易日 |
| `--interval` | `1m` / `5m` / `1d`。**一定要給**，預設是 `1d` 不是 `1m` |
| `--balance` | 起始現金 |
| `--strategy` | 僅內建路徑：`BollingerStrategy` / `SupportResistanceStrategy` / `DCA_Monthly` / `DonchianBreakoutStrategy` / `ADXAdaptiveStrategy` / `BaselineStrategy` |
| `--file` | 僅自訂路徑：你的策略 `.py` |
| `--class` | 僅自訂路徑：檔案裡有多個策略類別時才需要 |
| `--params` | `'key:val,key:val'` |
| `--no-browser` | 內建路徑必加 |

### 4.3 `insight` — 結構化報告

```bash
uv run insight --list                  # 列出本機所有 run
uv run insight                         # 最近一次
uv run insight 5234b4ec                # 用 session id 前綴
uv run insight 5234b4ec --out /tmp/x   # 指定輸出目錄
uv run insight 5234b4ec --stdout       # 同時印出 markdown
```

產出 `<stem>.insight.md`（給你讀）和 `<stem>.insight.json`（給程式解析）。

**JSON 結構**（`run.sh` 已抽出主要欄位到 CSV，深入診斷時直接讀 JSON）：

| key | 內容 |
|---|---|
| `performance` | **驗收指標都在這裡**：`sharpe` `sortino` `calmar` `cagr` `volatility_annual` `max_drawdown` `time_in_market` `flat_periods` `observations` `winning_periods_pct` `value_at_risk_95` `cvar_95` `skew` `kurtosis` `ulcer_index` `recovery_factor` |
| `performance.monthly_returns` | **完整月報酬矩陣 + 每年 EOY。**要看獲利有沒有集中在某幾個月，先讀這個 |
| `performance.drawdowns[]` | 每一段完整回撤：`start` `valley` `end` `days` `max_drawdown` |
| `performance.tearsheet.metrics` | 約 75 個 quantstats 指標：`6m` `1y` `3y_ann` `longest_dd_days` `max_consecutive_losses` `win_month` `worst_month` `kelly_criterion` `risk_of_ruin` `payoff_ratio` `tail_ratio` 等 |
| `provenance` | **哪條路徑產生的**、interval、標的、視窗、bar 數、完整參數、成本模型、執行模型敘述、`start_was_explicit` |
| `findings[]` | `{severity, what, evidence, why}`。**先看這個**，它會主動指出獲利集中在少數幾天 |
| `run` | 期間、初始/最終現金與權益、`net_pnl`、`turnover` |
| `activity` | 成交筆數、買賣、成交額、手續費/稅/滑價、`fee_floor_fills`、中位委託金額 |
| `round_trips` | 筆數、勝率、gross、`profit_factor`、持有天數分布、最長連敗 |
| `market.symbols` | 每檔的 session 數、bar 數、價格區間、波動、regime 天數分布、`weekdays_without_bars` |
| `by_regime` | trending / neutral / ranging 各自的 P&L 與勝敗天數 |
| `by_day[]` | 每個交易日：regime、trendiness、漲跌、波動、成交、P&L |
| `cannot_see` / `caveats` | 這份報告看不到什麼、這些數字會怎麼騙你 |

`provenance` 是必讀的，它排在所有數字之前，因為它決定那些數字該怎麼讀。

### 4.4 `strategy-tool` — 策略腳手架

```bash
uv run strategy-tool templates                           # 有哪些範本
uv run strategy-tool template --kind bb --name MyStrat --symbol 2317
uv run strategy-tool check --file path/to/strategy.py    # 注意是 --file，不是位置參數
uv run strategy-tool api                                 # 可用的所有名稱
```

`--kind` 可選 `bb` / `dca` / `adx` / `blank`。`template` 輸出 **JSON**，程式碼在 `source` 欄位：

```bash
uv run strategy-tool template --kind bb --name MyStrat --symbol 2317 | jq -r .source
```

**注意**：`check` 在「你的程式有錯」時仍然 exit 0，非零代表工具本身壞了。要判斷結果請解析輸出內容。

**重要**：`strategy-tool` 的範本是給 trading engine 的 `authoring` API（`on_bar(bar, account)` + `ta.*` + `param.*`），**那套不能用 `custom_backtest.py` 跑**。要跑快速回測，請照第 5 節的 `BaseStrategy` 介面寫。範本的價值在於看策略邏輯長什麼樣子，以及 `strategy-tool api` 列出的指標清單可以當靈感。

### 4.5 明確禁止

| 不要做 | 原因 |
|---|---|
| 為了找 root cause 去讀框架 source code | 你的角色是使用者。發現怪異行為就記錄（第 8.4 節），不要追進去 |
| 連網查價格、新聞、財報 | 資料已全部預熱在本機，不需要連網。這是實驗設計的一部分 |
| 用 trading engine（`poc/trading_engine/main2.py`） | 太慢。一次最多 300 天、只支援 1m、每次數分鐘。這個實驗不需要它 |
| 碰 OOS 區間（2025-01-01 之後）做調參 | 那是驗收資料。只能在 P5 碰一次 |
| 用 `DCA_Monthly` / `BaselineStrategy` 當答案 | 違反低曝險目標。只能當基準對照 |
| 改 `exp/bin/windows.sh` 的清單 | 預先登錄的意義就在於不能改 |
| 設 `CJTRADE_HOME` | 會一起隔離掉憑證，broker 起不來 |
| 手改或刪除 `exp/runs.csv` 的列 | 只增不改。刪掉難看的結果就是在騙自己 |

**第 5 節的「寫自己的策略」不算越界。** 界線是「不要為了 debug 框架去讀它的實作」，不是「不准寫程式」。第 5 節就是完整的策略撰寫契約，照著寫就夠，不需要打開框架任何檔案。

---

## 5. 自己寫策略

內建策略的所有回看期都被 schema 限制在 **100 根 bar 以內**。在 1m 上那是 100 分鐘，所以**內建策略在 1m 上不可能表達日線級的想法**。第 6.7 節的實測基準顯示它們在 1m 上全部被成本摧毀。

要做出低曝險的波段策略，你必須自己寫。**先從內建策略和 `example_breakout.py` 開始測**，確認你理解基準在哪裡，再開始自己設計。

以下是完整契約，**不需要去讀 source code**。

### 5.1 最小可用骨架

```python
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy, Signal

BARS_PER_DAY = 270  # 台股 09:01–13:30

class MyStrategy(BaseStrategy):
    name = "MyStrategy"                      # 會出現在報告裡

    def on_start(self, ctx):                 # 每次 run 開始前呼叫一次
        self.entry_price = None

    def on_bar(self, bar, ctx):              # 每根 bar 呼叫，回傳 list[Signal]
        lookback = int(ctx.params.get("lookback", 20 * BARS_PER_DAY))
        closes = ctx.prices(bar.symbol)
        if len(closes) < lookback + 1:
            return []                        # 暖機中
        ...
        return []

    def on_fill(self, fill, ctx): pass       # 每次成交後呼叫（選用）
    def on_end(self, ctx): pass              # 最後一根 bar 之後呼叫一次（選用）
    def monitors(self): return {}            # 想被觀察的數值（選用，會進報告）
```

生命週期：`on_start` → 每根 bar `on_bar` → 成交就 `on_fill` → 跑完 `on_end`。

### 5.2 `bar` 有什麼

| 屬性 | 型別 | 說明 |
|---|---|---|
| `bar.timestamp` | `datetime` | 這根 bar 的時間 |
| `bar.open` `bar.high` `bar.low` `bar.close` | `float` | OHLC |
| `bar.volume` | `int` | 成交量 |
| `bar.symbol` | `str` | 標的代號 |

### 5.3 `ctx`（`StrategyContext`）有什麼

| 屬性 / 方法 | 說明 |
|---|---|
| `ctx.timestamp` | 當前 bar 時間 |
| `ctx.balance` | 可用現金 |
| `ctx.equity` | 現金 + 所有持倉市值 |
| `ctx.positions` | `list[dict]`，每個含 `symbol` `quantity` `avg_cost` `current_price` `market_value` `unrealized_pnl` |
| `ctx.bar_index` | 當前 bar 的 0-based 索引 |
| `ctx.params` | **你用 `--params` 傳進來的 dict**，不做 schema 驗證，key 自己取 |
| `ctx.prices(symbol)` | **到目前為止的收盤價 list，最新在最後，沒有長度上限** |
| `ctx.has_position(symbol)` | `bool` |
| `ctx.position_qty(symbol)` | `int`（**股數**） |

`ctx.prices()` 的無上限回看就是關鍵：在 1m bar 上要做 20 日突破，就看 `closes[-(20*270+1):-1]`。

**只有收盤價有歷史。** `bar.high` / `bar.low` 只有當根。需要真實的區間高低點，要自己在 `on_bar` 裡累積。

### 5.4 下單：`Signal`

```python
Signal(action, symbol, quantity, price, reason="", meta={})
```

- `action`：`"BUY"` / `"SELL"` / `"HOLD"`（HOLD 只被記錄，不會成交）
- `quantity`：**股數，不是張數**。要用 50% 權益就是 `int(ctx.equity * 0.5 / bar.close)`
- `price`：送出的價格
- `reason`：會進 `fill_history` 和報告，**務必填**，這是之後診斷決策的唯一線索

### 5.5 執行語義（必讀）

- **訊號在產生它的那根 bar 內、以訊號自己的價格成交。**沒有限價檢查、沒有延遲。
- BUY 在**現金不足**時被丟棄，SELL 在**持股不足**時被丟棄，**兩者都是靜默的**。下單前自己檢查 `ctx.balance` 和 `ctx.position_qty()`，並在 `monitors()` 裡回報被拒次數。
- 沒有風控閘、沒有單 bar 下單上限、沒有回撤熔斷。**你的策略就是全部的風控。**
- 權益曲線每分鐘記錄一點。

### 5.6 成本模型（預設值，不可改）

| 項目 | 值 |
|---|---|
| 手續費 | 每邊 0.1425%，**無折扣**，最低 NT$20 |
| 證交稅 | 賣出 0.3%（股票）／ 0.1%（ETF，代號開頭為 `0`） |
| 滑價 | `none`（預設不套用） |

**來回成本：股票 0.585%、ETF 0.385%。**

這個數字決定了可行的交易頻率。1 分鐘級的中位波動約 27 bp（0.27%），所以**任何平均持有時間短到無法賺超過 0.585% 的策略，數學上就是賠的**。第 6.7 節的基準表就是這個現象的直接證據。

### 5.7 效能提醒

`on_bar` 會被呼叫 25 萬次以上（1m 全 IS 期間 258,138 根）。每根都對 5,400 個元素做 `max()` 的話，整次 run 約 28 秒。可以接受，但要掃很多參數時請維護增量狀態（例如滾動極值）而不是每根重算。

### 5.8 可直接跑的範例

`exp/strategies/example_breakout.py`：在 1m bar 上做日線級突破，多日回看、持有數天、不在趨勢中就空手。

```bash
./exp/bin/run.sh demo 2317 exp/strategies/example_breakout.py 1m 2021-01-01 1461 \
  'lookback:5400,exit_lookback:2700,pos_pct:0.5'
```

未調參的結果是 `sharpe=0.667907 cagr=+5.89% TiM=30%`，**但第 0.4 節已經證明這個數字靠一個分段撐起來**。它是你的起點和反面教材，不是答案。

---

## 6. 地雷（實測，不是推測）

### 6.1 第一次觸碰新的（標的, interval, 區間）組合會回 0 根 bar ⚠️ 最重要

broker 重啟後第一次請求某個（標的, interval, 區間）組合，可能回傳 **0 根 bar**，接著 `RuntimeError: No kbars found`。重試一次就成功。

這是整個實驗最危險的陷阱：**0 根 bar 如果被當成「策略沒有交易」記錄下來，跟真實結果無法分辨。**

`run.sh` 已經處理：自動重試 3 次，並且永遠不把 0 bar 的 run 標成 `ok`（標 `NO_KBARS`）。**這就是為什麼你必須用 `run.sh`，不要直接呼叫底層 CLI。**

實測：穩定狀態下同一條指令跑 12 次，`bars=258138`、`final equity 887,744.00`，**12/12 完全一致**。可重現性是好的，問題只發生在 coverage 狀態剛變動時。

**如果重試 3 次仍然 0 bar**，執行復原程序：

```bash
pkill -f "arenaxd --backend=backtest"; sleep 3
sqlite3 ~/Library/Caches/cjtrade/arenax_price.db \
  "DELETE FROM arenax_symbol_coverage WHERE symbol='<標的>' AND timeframe='<interval>';"
# 然後照 3.3 節重啟 broker
```

這只清掉「已抓取範圍」的快取，價格資料本身不動。實測有效。

### 6.2 不要請求早於 2020-03-02 的起始日

實測這會污染 broker 的記憶體狀態，**之後該標的的所有查詢都靜默回傳 0 或被截斷的資料，直到重啟 broker**。發生過：2317 的 1d 查詢在 267 筆資料確實存在的情況下回傳 0。

**每一次 run 都要檢查 CSV 裡的 `bars` 欄位。** bar 數突然改變就是出事了。用 `EXPECT_BARS` 可以自動抓到：

```bash
EXPECT_BARS=258138 ./exp/bin/run.sh e001 2317 ... 1m 2021-01-01 1461 '...'
```

常用組合的正確 bar 數（2317）：

| interval | start | duration | bars |
|---|---|---|---|
| `1m` | 2021-01-01 | 1461 | 258,138 |
| `5m` | 2021-01-01 | 1461 | 53,399 |
| `1d` | 2021-01-01 | 1461 | 970 |

IS 8 個分段（2317，1m）的正確 bar 數依序為：31,385 / 33,752 / 31,343 / 34,303 / 30,317 / 33,744 / 31,372 / 32,984。

### 6.3 不要在同一個 Python process 裡重複呼叫資料 API

實測在單一 process 內連續取資料，**後面的呼叫會對有完整資料的區間回傳 0**。`run.sh` 每次 run 都開新 process，所以不會遇到。

**不要自己寫 Python harness 來跑多次回測。** 用 shell 迴圈呼叫 `run.sh`。

### 6.4 `--interval` 會連帶換掉整組預設參數

不只是 bar 大小。實測 `1d` → `1m`：`bb__window_size` 20→100、`adx__period` 14→25、門檻 40/20→30/15、`donchian__period` 20→80、`risk__max_position_pct` 0.05→0.03。

**固定 interval 再掃參數，不要兩個一起變。**

### 6.5 `BaselineStrategy` 在本金不足時完全不交易

`BaselineStrategy` 內部寫死每月買入 NT$4,888,888。用 `--balance 1000000` 跑會得到 **0 fills、Sharpe nan**，而且是靜默的。

要當基準用，**本金必須設 10,000,000**：

```bash
BAL=10000000 ./exp/bin/run.sh bench 0050 BaselineStrategy 1d 2023-03-01 660 ''
```

實測這樣會得到 1 筆成交（開頭全押），即 buy&hold。該視窗結果：**Sharpe 1.3748 / CAGR 16.56% / MDD -13.44%**。

Sharpe、CAGR、MDD 都是比率，與本金無關，所以用不同本金跑基準是可以比較的。

### 6.6 內建策略的參數上限

| 參數 | 範圍 | 備註 |
|---|---|---|
| `bb__window_size` | 5–100 | |
| `bb__std_dev` | 1.0–3.0 | |
| `bb__min_width_pct` | 0.001–0.1 | |
| `donchian__period` | 5–100 | |
| `donchian__trailing_stop_pct` | 0.0–0.5 | **實測無效，見 O003** |
| `donchian__breakout_mode` | `close` / `touch` | |
| `adx__period` | 5–50 | |
| `adx__strong_threshold` | 20.0–60.0 | |
| `adx__weak_threshold` | 10.0–40.0 | |
| `adx__donchian_period` | 5–100 | |
| `adx__snr_lookback_days` | 1–100 | |
| `adx__snr_threshold_pct` | 0.001–0.1 | |
| `sr__lookback_days` | 1–100 | |
| `sr__support_threshold_pct` | 0.001–0.1 | |
| `sr__resistance_threshold_pct` | 0.001–0.1 | |
| `sr__breakout_mode` | `True` / `False` | |
| `sr__interval` | 固定值，不可覆寫 | |
| `dca__buy_frequency_months` | 1–24 | 不要用 DCA |
| `dca__max_position_pct` | 0.01–0.5 | 不要用 DCA |
| `risk__max_position_pct` | **0.01–0.5** | 所有策略共用；這是曝險主要旋鈕 |

超出範圍會直接 **raise**，不是靜默忽略。共 20 個參數。

`--show-params` 可以看某個 interval 的完整預設值，但**它會忽略 `--strategy`**，所以 `Strategy:` 標籤和 `Params Hash` 不對，參數清單本身是對的。

### 6.7 內建策略在 IS 期間的實測基準（2317，2021-01-01 +1461 天）

這是你要超越的對象。全部 `risk__max_position_pct:0.5`，其餘參數預設：

| interval | strategy | Sharpe | CAGR | MDD | TiM | trips |
|---|---|---|---|---|---|---|
| `1m` | Bollinger | -0.36 | -3.61% | -17.4% | 78% | 463 |
| `1m` | Donchian | -6.42 | -50.91% | -93.5% | 85% | 578 |
| `1m` | ADXAdaptive | -3.95 | -49.11% | -93.1% | 83% | 2255 |
| `1m` | SupportResistance | +0.01 | -0.36% | -10.7% | 47% | 18 |
| `5m` | Bollinger | -0.36 | -3.73% | -19.7% | 83% | 491 |
| `5m` | Donchian | -7.72 | -60.62% | -97.3% | 89% | 743 |
| `5m` | ADXAdaptive | -2.13 | -23.33% | -65.7% | 73% | 427 |
| `5m` | SupportResistance | -5.57 | -70.16% | -99.1% | 78% | 2564 |
| `1d` | Bollinger | +0.21 | +1.59% | -9.9% | 47% | 10 |
| **`1d`** | **Donchian** | **+0.51** | **+4.08%** | **-16.2%** | **32%** | **16** |
| `1d` | ADXAdaptive | -0.03 | -1.07% | -33.0% | 47% | 30 |
| `1d` | SupportResistance | -0.04 | -0.86% | -11.8% | 48% | 27 |

**沒有任何內建策略通過驗收。** 最好的是 1d Donchian（Sharpe 0.51 / CAGR 4.08% / TiM 32%）。

可以讀出來的規律：**1m 和 5m 上所有內建策略都被成本摧毀**（TiM 73–89%，Sharpe 深度為負），因為 100 根 bar 的回看上限強迫它們過度交易。到了 1d，行為變成波段，TiM 掉到 32–48%，Sharpe 轉正。

### 6.8 已知修好的（跟舊結果比對會對不上，那是修好而非迴歸）

- `bb__std_dev` 之前完全無效（寫死 2，且 schema 標 `fixed` 使覆寫被丟棄）
- `dca__max_position_pct` 之前無效；`dca__buy_frequency_days` 換成 `dca__buy_frequency_months`
- Donchian 之前零成交（lookback 誤乘 bars_per_day；且通道含當前 bar 使突破不可能成立）
- ADX 的 TREND 通道有同一個 off-by-one
- `kbars()` 之前無條件把整個請求範圍標為「已覆蓋」即使回 0 筆

---

## 7. 實驗流程

### 7.0 可行性算術（先看這個，知道自己在追什麼）

設 `f` = time in market，`pos` = 持倉時的部位佔權益比例（上限 0.5），`r` = 持倉期間標的的年化報酬。大致上：

```
CAGR ≈ f × pos × r
```

| f | pos | 需要的 r |
|---|---|---|
| 0.20 | 0.5 | 50% / 年 |
| 0.10 | 0.5 | 100% / 年 |
| 0.05 | 0.5 | 200% / 年 |

所以 **TiM 10% + CAGR 5% 要求你選中的那 10% 時間裡標的年化跑 100%**。苛刻，但這正是選擇性策略的意義：你不是要賺整段行情，你是要只參與其中最陡的那一小段。

Sharpe 方面：`Sharpe ≈ sqrt(f) × (持倉期間的每日 Sharpe) × sqrt(252)`。**降低 f 會傷害 Sharpe**，必須靠提高 `pos` 和提高進場品質來補。這是 TiM 和 Sharpe 之間的真實張力，不要期待兩者同時衝到「優秀」。

**實務上先瞄準這一區**：`f ≈ 0.10–0.20`、`pos = 0.5`、平均持有 2–6 週、每年 3–8 筆交易。站穩之後再往 `f ≤ 0.10` 推。

### 7.1 搜尋目標函數

不要用全期 Sharpe 當搜尋目標，它會獎勵第 0.4 節那種一次好運。

> **主要目標：最大化 8 個 IS 分段中「最差分段的報酬」**
> **約束：IS 全期 CAGR ≥ 5%、TiM ≤ 20%、round trips ≥ 10**

最大化最差情況比最大化平均難曲線配適得多，而且直接編碼了「穩定」這個要求。

次要目標（打破平手，依序）：① TiM 更低 ② 全期 Sharpe 更高 ③ MDD 更淺。

### 7.2 階段

| 階段 | 做什麼 | 區間 | 預算 |
|---|---|---|---|
| **P0** | 環境健康檢查（3.4）＋抽驗 6.7 節基準表 3 列確認一致 | IS 全期 | ~5 runs |
| **P1** | 內建策略篩選：5 個非 DCA 策略 × 3 個 interval | IS 全期 | ~15 runs |
| **P2** | 選一檔標的、寫自訂策略。從 `example_breakout.py` 開始改 | IS 全期 | ~60 runs |
| **P3** | 粗網格調參：**最多 3 個參數**，每個最多 5 個值 | IS 全期 | ~125 runs |
| **P4** | 前 5 名各跑 8 個 IS 分段（7.1 的目標函數）＋高原檢查（7.3） | IS 分段 | ~120 runs |
| **P5** | **OOS 驗收**：最終候選跑 OOS 全期 ＋ **4 個獨立分段** ＋ 17 個滾動視窗 ＋ 0050 基準 | OOS | ~45 runs |
| **P6** | STRESS：2020 疫情崩盤分段 | STRESS | ~10 runs |

**總預算約 400 次 run。** 超過就在日誌裡說明理由。這個上限是防過配的硬性限制，不是方便性考量：用 258,138 根 bar 和一堆旋鈕，跑幾千次必然找到一組「IS 漂亮、OOS 一文不值」的參數。

**P5 通過（4 個獨立分段 ≥3/4 為正、最差 ≥ -10%）才算實驗完成。**

### 7.3 參數高原要求

選定的參數組**必須落在高原上，不能是尖峰**。對最終候選的每一個參數，往上下各動一格（約 ±20%），共 2N 個鄰居。要求：

- **所有鄰居的最差 IS 分段報酬 ≥ 最佳值的 70%**
- **所有鄰居的 IS 全期 CAGR 仍為正**

任何鄰居掉下懸崖，就代表這組參數是曲線配適的產物。**丟掉它，選次佳的高原。**

這一步很便宜（3 個參數 = 6 次 run × 8 分段），而且是你手上最有效的防過配工具。

### 7.4 標的選擇規則

**先選一檔，整個實驗都用它。** 預設建議 `2317`（資料最完整，1m 覆蓋 1,630 個交易日）。

如果要換標的，**每換一檔就是一次完整的多重比較**，必須在日誌記錄理由，而且**最多換 2 次**。在 7 檔標的上各試一輪再挑最好的，等於做了 7 次獨立實驗只報告最好的那次，OOS 必然失望。

### 7.5 隨機起始日盲測（輔助，P5 之後）

原始構想裡「不指定 `--start`」的機制，保留為輔助盲測。規則：

1. **跑完 P5 之後才做**，次數預先登錄：**20 次，不多不少**
2. 每次都要記錄，包含 `RuntimeError` 失敗的和落在 IS 的
3. 從 `insight` 的 `provenance.requested_start` 讀出實際被抽到的日期，分類成 IS / OOS / 無資料
4. **看到結果之後不准重抽。** 抽到難看的數字就是結果的一部分

`custom_backtest.py` 的 `--start` 是必填的。所以最終策略若是自訂的，改成**先在日誌寫下 20 個日期，再執行**，先寫後跑、全部回報，效果等價且可稽核。

---

## 8. 紀錄規範

這個實驗會跨很多個工作階段，可能連續很長時間。**找不回來的結果等於沒做。** 以下是強制規範。

### 8.1 三份檔案，各有分工

| 檔案 | 寫什麼 | 怎麼寫 |
|---|---|---|
| `exp/runs.csv` | 每一次 run 一列 | `run.sh` 自動，只增不改，**永遠不要手改或刪列** |
| `exp/logs/JOURNAL.md` | **實驗日誌**：你的心路歷程 | 手寫，往下追加，見 8.2 |
| `exp/logs/OBSERVATIONS.md` | 框架怪異行為 | 手寫，見 8.4 |

### 8.2 實驗日誌 `exp/logs/JOURNAL.md`

每一個決策點都要有一筆。格式固定，方便之後搜尋：

```markdown
## [E012] 2026-11-13 14:30 — 把 exit_lookback 從 2700 降到 1350

**當時狀況**：E011 得到 sharpe 0.71 / cagr 6.2% / TiM 31%，最差 IS 分段 -4.8%。TiM 太高。

**假設**：出場太慢，部位在趨勢結束後還抱著。縮短出場回看應該能壓低 TiM。

**做了什麼**：`./exp/bin/run.sh e012 2317 exp/strategies/breakout_v3.py 1m 2021-01-01 1461 'lookback:5400,exit_lookback:1350,pos_pct:0.5'`

**結果**：sharpe 0.58 / cagr 4.1% / TiM 24% / trips 31（sid `a1b2c3d4`）

**讀出什麼**：TiM 確實降到 24%，但交易筆數從 16 跳到 31，成本吃掉 2.1pp 的 CAGR。
出場太敏感，被洗出場又追回去。

**下一步**：出場改用追蹤停損而不是通道下緣，試 8% / 12%。
```

規則：

- **編號連續**（`E001`、`E002`…），和 `run.sh` 的 `tag` 對應，這樣 CSV 和日誌能互相查找
- **每一筆都要有「假設」和「讀出什麼」**。只貼數字的日誌，三天後你自己也看不懂當時在想什麼
- **失敗的嘗試一定要記錄。** 沒記錄的失敗會被重複做
- 想法轉向、放棄某個方向，都要寫下理由

### 8.3 階段檢查點

每個階段（P0–P6）結束時，在 JOURNAL 寫一段檢查點：

```markdown
# === CHECKPOINT P4 完成 2026-11-13 18:00 ===
累計 run 數：312 / 400
目前最佳：breakout_v5 `lookback:4050,exit:2025,pos:0.5` (sid 7f3e1a2b)
  IS 全期：sharpe 1.12 / cagr 6.8% / TiM 16% / trips 19
  IS 8 分段：7/8 為正，最差 -3.2%，最大單段佔總損益 34%
  高原檢查：6 個鄰居全部通過
距離目標：Sharpe 1.12（良好 1.25 還差 0.13），TiM 16%（優秀 5% 還有距離）
已排除：純通道出場（太敏感）、2412（CAGR 到不了 5%）、1d interval（TiM 壓不下 30%）
下一步：P5 OOS 驗收
```

長時間工作時，**每次重新進入狀況就先讀最後一個 checkpoint**，不要重讀整份日誌。

### 8.4 觀察紀錄 `exp/logs/OBSERVATIONS.md`

遇到框架怪異行為就記在這裡，**然後繼續做你的實驗**。不要追查原因、不要讀 source code、不要試圖修。專門修框架的人看到就會處理。

該檔案已預先記錄 9 條（O001–O009），包含 0-bar 陷阱、`donchian__trailing_stop_pct` 無效、`BaselineStrategy` 靜默不交易等。**那些不用重複記。**

格式：

```markdown
## [O010] <一句話現象>

**現象**：...
**證據**：具體參數、具體數字、sid
**影響**：這會怎麼影響實驗（例如「不要掃這個參數」）
```

### 8.5 策略檔版本管理

每個策略版本存成獨立檔案，**不要覆寫**：

```
exp/strategies/breakout_v1.py
exp/strategies/breakout_v2.py
...
```

CSV 的 `params` 欄位記錄了參數，`provenance.strategy_file` 記錄了檔案路徑，所以任何一列都能完整重現。**覆寫檔案會讓舊的 run 永久失去意義。**

### 8.6 隨時找回資料

```bash
./exp/bin/report.sh                  # 所有 run
./exp/bin/report.sh --pass           # 只看通過門檻的
./exp/bin/report.sh --bad            # 只看沒產出結果的（NO_KBARS 等）
./exp/bin/report.sh e012             # 某個 tag
uv run insight <sid> --stdout        # 某次 run 的完整報告
grep -n "E012" exp/logs/JOURNAL.md   # 某個決策點
```

---

## 9. 最終交付

全部做完後，在 `exp/logs/JOURNAL.md` 最後寫一份總結：

1. **最終策略**：檔案路徑、參數、標的、interval
2. **IS 全期數字**：Sharpe / CAGR / TiM / MDD / trips，逐條對照 0.1 節的三級目標
3. **IS 8 個分段的完整表格**：每段的報酬、TiM、trips。加上「最大單段佔總損益比例」
4. **OOS 全期數字** ＋ **4 個獨立分段的完整表格**（這是驗收核心）
5. **OOS 17 個滾動視窗的分布**：正報酬視窗數、最差視窗、月報酬矩陣。不是只報平均
6. **0050 基準對照**：同期間、同分段
7. **高原檢查結果**：2N 個鄰居的數字
8. **2020 壓力測試結果**
9. **權衡曲線**：你試過的候選在 (TiM, Sharpe, CAGR) 上的分布，讓人可以自己選點
10. **心路歷程摘要**：試過哪些方向、為什麼放棄、關鍵轉折是哪一次
11. **這套策略會在什麼情況下失效**：你比任何人都清楚它的弱點，寫出來
12. **觀察到的框架問題**：指向 `OBSERVATIONS.md`

### 誠實回報的義務

如果跑完 400 次 run 仍然達不到最低門檻，**就這樣回報**。寫清楚最接近的結果、卡在哪一個門檻、以及你認為為什麼達不到。

一個誠實的「在這個成本結構下，用 400 次 run 的預算達不到，最佳為 Sharpe 0.85 / CAGR 5.2% / TiM 26%，最差 IS 分段 -6.1%」，比一個靠 3,000 次 run 挑出來、OOS 立刻崩掉的「成功」有價值得多。

**OOS 只能碰一次。** 不要為了讓數字過關而反覆重跑驗證集 —— 那會讓 OOS 變成第二個訓練集，整個實驗就失去意義了。
