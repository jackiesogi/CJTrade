# 執行交易引擎

[一次性回測（oneshot）](backtesting.md)速度快但經過簡化。交易引擎 `cjtrade` 以實盤的方式執行策略：依 ArenaX 的時鐘逐分鐘推進，並真實撮合委託。本頁在離線狀態下重播一檔股票一週的 1 分 K，並說明報告內容。

## 引擎在做什麼

```mermaid
flowchart TB
    subgraph E["cjtrade（主程序）"]
        direction TB
        R["風控閘門"]
        K["回放時鐘"]
        CL["券商連線"]
    end
    subgraph Bots["Bot：每個一個程序、一檔股票"]
        direction TB
        B1["Bot_B · 2357"]
        B2["Bot_U · 你的策略檔"]
    end
    K -- "最新收盤的 K 棒" --> B1 & B2
    B1 & B2 -- "buy / sell / hold" --> R
    R -- "通過檢查的委託" --> CL
    CL <-- "委託、成交、帳戶" --> AX["ArenaX"]
```

每一根 K 棒的流程：

```mermaid
sequenceDiagram
    participant Clock as 回放時鐘
    participant Main as cjtrade（主程序）
    participant Bot as Bot
    participant AX as ArenaX
    Clock->>Main: 下一根 K 棒的時間
    Main->>AX: 取得到該時間為止已收盤的 K 棒
    Main->>Bot: 最新收盤的 K 棒
    Bot-->>Main: buy / sell / hold
    Main->>Main: 風控閘門檢查
    Main->>AX: 下單（通過檢查時）
    Main->>AX: 更新掛單與帳戶
    Main-->>Bot: 成交回報
    Note over Main,Bot: 等所有 bot 回覆後才前進到下一根
```

- 每個策略以一個 **bot** 的形式在獨立的 process 中執行，只負責一檔股票。
- bot 不直接和券商溝通，而是回應主程式；主程式讓每筆委託先通過**風控閘門**（每個 bot 的資金額度、每根 K 棒最多 3 筆委託、帳戶回撤 25% 即停止）才送出。
- 引擎等所有 bot 回應後才推進，因此不論重播速度多快，每次產生的委託都相同。

執行哪些 bot 由 [`src/cjtrade/apps/CJTrade/main.py`](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/apps/CJTrade/main.py) 中的 `BOT_ROSTER` 決定。預設只有一個 bot `Bot_B`，以 ADX 盤勢切換策略交易 `2357`（華碩）。要換成自己的策略檔，見[執行你自己的策略](#run-your-own-strategy)。

## 第 1 步：下載價格

把 2357 三週的 1 分 K 下載到檔案。只有這一步需要網路：

```sh
uv run preload-prices --price-db prices.db --symbols 2357 --start 2026-11-02 --end 2026-11-21 --interval 1m,1d
```

時間區間必須在最近 30 天內，這是免費分 K 來源 Yahoo Finance 的保留上限。

預期輸出：

```text
2357 1m: 3639 bars over 15 days (2026-11-02 09:01 .. 2026-11-20 13:25)
2357 1d: 15 bars over 15 days (2026-11-02 09:00 .. 2026-11-20 09:00)
3654 bars in prices.db
```

## 第 2 步：用這個檔案啟動 ArenaX

在另一個終端機：

```sh
CJTRADE_OFFLINE=1 AX_INITIAL_BALANCE=1000000 uv run arenaxd --backend=backtest --data=offline --price-db=prices.db
```

| 部分 | 意思 |
|---|---|
| `CJTRADE_OFFLINE=1` | 不連網；任何下載都會失敗 |
| `AX_INITIAL_BALANCE=1000000` | 模擬帳戶期初 NT$1,000,000（預設 100,000） |
| `--backend=backtest` | 重播模式；監聽 port **8802**，即引擎預期的 port |
| `--data=offline --price-db=prices.db` | 只從檔案讀取價格 |

等待 `sim env started`（約 20 秒）。在此之前出現 `no fetchable history found in 30 attempts` 屬正常：伺服器無法自行選定起始日，會等引擎指定。

## 第 3 步：執行引擎

在第二個終端機：

```sh
uv run cjtrade --broker=arenax --mode=backtest --watch-list=2357 --fund=1000000 --days=5 --start-date=2026-11-03 --speed=0
```

| 選項 | 意思 |
|---|---|
| `--broker=arenax` | 在 ArenaX 上交易 |
| `--mode=backtest` | 連到 port 8802 的 `backtest` 伺服器（`demo` 是 8801，`paper` 是 8803） |
| `--watch-list=2357` | 要餵給 bot 的股票；每個 bot 的股票都必須列入 |
| `--fund=1000000` | bot 計算下單數量所依據的資金 |
| `--days=5` | 重播天數 |
| `--start-date=2026-11-03` | 起始日；省略則隨機選一天 |
| `--speed=0` | 不限速；`60` 代表每一秒實際時間推進一分鐘市場時間 |

!!! tip "不填的選項會問你"
    省略的選項，引擎會在終端機中詢問並預填預設值，回答會保留供下次使用。

預期輸出（節錄）：

```text
[INFO][...] engine: broker=arenax backend=backtest clock=replay symbols=2357 fund=1000000 days=5
[INFO][...] engine.clock: replay: 961 bars, 2026-11-03 09:01:00 .. 2026-11-06 13:25:00, flat out (no pacing)
[INFO][...] engine: spawned Bot_B (bot_b.py, 2357)
[INFO][...] bot.Bot_B: started (2357) strategy=ADX_Adaptive
[INFO][...] engine: @2026-11-03 09:34 FILLED BUY 2357 x218/218 px=915.0 for Bot_B (resolved on refresh) balance=800246
[INFO][...] engine: @2026-11-03 10:04 FILLED SELL 2357 x218/218 px=908.0 for Bot_B (resolved on refresh) balance=997314
...
[INFO][...] engine: replay done: 960 bars in 12.6s (76 bars/s)
==================================================
  Backtest Summary
==================================================
  PnL (Total)  :      -76,768.08  (-7.68%)
  Total fills  : 13
  Max drawdown : -7.21%
  Round trips  : 9  (win 0 / loss 9,  win rate 0.0%)
  ...
[INFO][...] engine.report: result saved: .../reports/engine_be329ab8.pkl
HTML saved -> .../reports/engine_be329ab8.html
```

說明：

- `replay: 961 bars` 是四個交易日的 1 分 K。`--days=5` 以日曆天計算（11 月 3 日到 7 日），而 7 日是星期六。
- `@2026-11-03 09:34` 是事件的「市場」時間；每行開頭方括號內是實際時間。
- `FILLED BUY 2357 x218/218 px=915.0`：委託 218 股，218 股全數以 915 成交。
- 摘要欄位與[一次性回測的報告](backtesting.md#read-the-summary)相同。這次執行虧損；預設的 bot 不適合那一週的行情。
- 結果存成 `.pkl` 檔和 HTML 報告，兩個路徑都會印出。

執行期間，狀態（bot、持股、最近的委託）提供於 <http://127.0.0.1:8898/status>。

結束後按 Ctrl+C 停止 ArenaX 伺服器。

## 第 4 步：用 `insight` 深入分析

`insight` 把一次執行的結果與同期間的價格合併，產生診斷報告：

```sh
uv run insight --list      # 這台電腦上的所有執行紀錄
uv run insight             # 最近一次
```

預期輸出：

```text
1 run(s) in .../reports:
  be329ab8                                 engine   2026-11-27 15:21     40,893 bytes

Run be329ab8 — 13 fill(s), 9 round trip(s), net -76,768.08
  Sharpe -10.754 · Sortino -10.147 · CAGR -99.81% · max drawdown -7.21%
  report  .../reports/engine_be329ab8.insight.md
  json    .../reports/engine_be329ab8.insight.json
```

完整分析見 `.insight.md` 檔。執行期間這麼短，CAGR 等年化數字沒有參考價值。

## 執行你自己的策略 {#run-your-own-strategy}

要把[撰寫策略](strategy.md)的策略檔當成 bot 執行，將它列在名單（roster）檔 `roster.json` 中：

```json
[
  {"bot_id": "Bot_U", "script": "bot_custom.py", "symbol": "2357",
   "extra": ["/absolute/path/to/my_strategy.py"]}
]
```

- `bot_id`：任意名稱，會出現在 log 中。
- `script`：`bot_custom.py`，即執行策略檔的 bot。
- `symbol`：交易的股票；也必須列入 `--watch-list`。
- `extra`：策略檔的**絕對**路徑。

然後在第 3 步的指令加上 `--roster=roster.json`。

## 其他模式

| `--mode` | ArenaX 的啟動方式 | 時鐘 |
|---|---|---|
| `backtest` | `uv run arenaxd --backend=backtest` | 重播指定期間，速度由 `--speed` 控制 |
| `demo` | `uv run arenaxd` | demo 伺服器自己的加速時鐘 |
| `paper` | `uv run arenaxd --backend=paper` | 真實時鐘，交易時段內，使用 Sinopac 即時價格 |

[FinHub 網頁介面](shell-and-finhub.md#finhub)會啟動 ArenaX 和引擎，並在瀏覽器中顯示同一次執行：

![在 FinHub Dashboard 上的一次執行](https://raw.githubusercontent.com/jackiesogi/CJTrade/master/doc/assets/img/finhub_dashboard.png)

下一步：[CJShell 和 FinHub](shell-and-finhub.md)。
