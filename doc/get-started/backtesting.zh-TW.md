# 回測

這一頁會拿一個策略，跑一整年台積電（2330）的真實價格，然後解讀結果。整個過程都在記憶體裡完成，不需要伺服器，幾秒鐘就跑完。

「回測」回答的是：「這個策略過去會怎麼做？」請記得，回測結果好不代表保證賺錢：過去不會完全重演，而且模擬永遠比真實市場寬容一點（見[回測沒有考慮到的事](#what-a-backtest-leaves-out)）。

## 執行內建策略

CJTrade 附有現成的策略。下面用 NT$1,000,000，拿布林通道策略跑 2024 年：

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.strategy.bb import BollingerStrategy

# 1. 從免費來源取得一年的日 K。
market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))
kbars = market.get_kbars("2330", "2024-01-01", "2025-01-01", "1d")
print("bars:", len(kbars))

# 2. 用這些 K 棒執行策略。
engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        params={"bb__window_size": 20})
result = engine.run(BollingerStrategy())

# 3. 印出摘要和每一筆交易。
report = BacktestReport(result)
report.summary()
report.print_round_trips()
```

- 第 1 步和[行情資料](market-data.md)裡的做法一樣。
- `params={"bb__window_size": 20}` 設定策略的參數。內建策略的參數名稱格式是 `<group>__<name>`；完整清單見[內建策略](../reference/strategies.md)。
- `engine.run(...)` 會一根一根走過 K 棒，問策略要怎麼做，再模擬每一筆委託。

預期輸出：

```text
bars: 242
==================================================
  Backtest Summary
==================================================
  Session      : N/A
  Start time   : 2024-01-02T09:00:00
  Init balance :    1,000,000.00
  Final balance:    1,016,806.00
  Final equity :    1,016,806.00
  PnL (Total)  :      +16,806.00  (+1.68%)
  rPnL         :      +16,806.00
  uPnL         :           +0.00  (+0.00%)
  Total fills  : 4
  Commission   :          307.65
  Tax (證交稅)  :          350.03
  Total cost   :          657.68
  Equity pts   : 242
  Sharpe ratio : 2.0471  (daily resolution, annualised)
  CAGR         : 1.76%
  Max drawdown : -0.50%
  Round trips  : 2  (win 2 / loss 0,  win rate 100.0%)
  Avg PnL/trip : +8,732.00
  Avg hold days: 38.5
==================================================
================================================================================
  Round-Trip History  (2 trades,  win 2 / loss 0,  total PnL +17,464.00)
================================================================================
    #  Symbol    Entry Date      Entry $  Exit Date        Exit $     Qty         PnL   Days
  ----------------------------------------------------------------------------
    1  2330      2024-04-19       750.00  2024-05-15       839.00      66    +5874.00    26d  🟢
    2  2330      2024-08-05       815.00  2024-09-25      1005.00      61   +11590.00    51d  🟢
================================================================================
```

同樣的 K 棒永遠得到同樣的結果，所以你看到的數字應該和上面一模一樣。

## 看懂摘要 {#read-the-summary}

| 欄位 | 意思 |
|---|---|
| Init balance / Final balance | 一開始和最後的現金 |
| Final equity | 現金加上還持有的股票市值 |
| PnL (Total) | 損益：最終權益減掉初始餘額 |
| rPnL / uPnL | 已實現損益（已經平倉的交易）和未實現損益（還持有的股票） |
| Total fills | 有幾筆委託成交；一買一賣（round trip）算兩筆成交 |
| Commission, Tax, Total cost | 這些成交付了多少手續費和稅 |
| Sharpe ratio | 報酬相對於帳戶價值波動的比例；一般認為大於 1 算不錯 |
| CAGR | 這個結果換算成的年化成長率 |
| Max drawdown | 從高點往下跌的最大幅度，以百分比表示 |
| Round trips, win rate | 先買後賣的配對次數，以及其中有幾次賺錢 |

這次執行中，策略交易了兩次，兩次都賺，扣掉成本後賺 +1.68%。它只買了 66 股和 61 股：內建策略預設只把帳戶大約 5% 的資金放進一筆持股，所以大部分的錢都留在現金。這就是為什麼和那年股價本身的漲幅相比，獲利顯得很小。

## 執行你自己的策略檔

[撰寫策略](strategy.md)裡的檔案載入之後，用法完全一樣：

```python
from pathlib import Path
from cjtrade.pkgs.strategy.user_strategy import load

strategy = load(Path("my_strategy.py").read_text())
result = BacktestEngine(kbars=kbars, symbol="2330",
                        initial_balance=1_000_000).run(strategy)

for f in result.fill_history:
    print(f["time"][:10], f["action"], f["quantity"], f["price"], f["reason"])
```

預期輸出：

```text
2024-04-19 BUY 66 750.0 lower band touch
2024-05-15 SELL 66 839.0 upper band touch
2024-08-05 BUY 61 815.0 lower band touch
2024-09-25 SELL 61 1005.0 upper band touch
```

因為 `my_strategy.py` 的規則和內建策略相同，所以交易也一樣。`reason` 就是你傳給 `buy()` 和 `sell()` 的文字。

## 儲存完整報告

```python
report.save_html("report.html")
print(report.metrics()["pnl_pct"])          # 所有數字，以 dict 形式取得
```

`report.html` 是一份完整的績效報告（tearsheet），裡面有帳戶價值、回撤和每月報酬的圖表。用瀏覽器打開就能看。`report.full_report()` 會寫出同一個檔案並幫你打開；在沒有瀏覽器的機器上，請傳入 `open_browser=False`。

## 交易成本

每筆成交都會付台灣證交所（TWSE）的交易成本：手續費是成交金額的 0.1425%，最低 NT$20；賣出時另收 0.3% 的證交稅（ETF 是 0.1%，也就是代號開頭是 `0` 的股票）。如果要模擬券商手續費折扣或滑價，可以傳入 `CostModel`：

```python
from cjtrade.pkgs.models.cost import CostModel

engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        cost_model=CostModel(commission_discount=0.6))   # 六折
```

所有選項見[成本模型](../reference/cost-model.md)。

## 回測沒有考慮到的事 {#what-a-backtest-leaves-out}

一次性回測（oneshot）之所以快，是因為它做了一些簡化：

- 根據某根 K 棒收盤價算出的訊號，會**在同一根 K 棒、用那個價格**成交，就算真實市場不一定給得了這個價格。
- 沒有成交量限制：多大的量都會一次成交。
- 沒有套用台股每日的漲跌停限制。

請把結果當成最好的情況。如果想要更接近真實的模擬，也就是逐分鐘、真的撮合委託，請用[交易引擎](trading-engine.md)。它算出來的數字通常比較低，所以比較兩者時，請看趨勢，不要比確切金額。

下一步：[執行交易引擎](trading-engine.md)。
