# CJTrade

CJTrade 是一套 Python 框架，用來交易台灣證券交易所（TWSE）的股票。你只要把交易想法寫成一個小小的 Python 檔，就能在不修改程式的情況下，用三種方式執行：

1. **用歷史價格跑**（也就是*回測*），看看這個想法過去表現如何。
2. **在模擬券商上跑**：模擬券商就在你自己的電腦上執行，你可以看它實際下單，又不必拿錢冒險。
3. **在正式券商帳戶上跑**（永豐金證券 Sinopac），等你信得過它再說。

這些都不需要券商帳戶就能試。[開始使用](get-started/install.md)裡的所有內容，都只用免費的價格資料，在你的電腦上就能執行。

!!! danger "這不是投資建議"
    CJTrade 可以在正式帳戶上送出真的委託，而它送出的每一筆委託都由你負責。請先在模擬券商上試策略，接著再到 Sinopac 的沙盒（模擬環境）試，確認沒問題後才動用真錢。

## 各個部分怎麼搭在一起

```
  your strategy file  ─┐
  (on_bar → buy/sell)  │
                       ▼
               ┌───────────────┐   orders, account    ┌──────────────────────┐
               │  CJTrade code │ ───────────────────▶ │ a broker             │
               │ (AccountClient│ ◀─────────────────── │  · ArenaX (pretend)  │
               │  or the engine)   fills, balance     │  · Sinopac (real)    │
               └───────────────┘                      └──────────────────────┘
                       ▲
                       │ prices (bars, quotes)
               ┌───────────────┐
               │ market data   │  Sinopac · FinMind · Yahoo · a local file
               └───────────────┘
```

- **券商**是委託送去的地方，你的現金和股票也放在這裡。**ArenaX** 是 CJTrade 內建的模擬券商：它是在你電腦上執行的一個小伺服器，會接收委託，並用真實的歷史價格讓委託成交。
- **行情來源**是價格的來源。它和券商是分開的，所以你可以在 ArenaX 上交易，同時使用 Yahoo Finance 的價格。
- **你的程式**只透過一個物件 `AccountClient` 和券商溝通。同樣的呼叫在 ArenaX 和 Sinopac 上都能用。

如果上面有不熟的詞，[基本概念](get-started/concepts.md)會用白話解釋。

## 選擇你的路線

| 你想要 | 從這裡開始 | 時間 |
|---|---|---|
| 安裝 CJTrade 並確認能用 | [安裝](get-started/install.md) | 5 分鐘 |
| 認識這些頁面用到的詞 | [基本概念](get-started/concepts.md) | 10 分鐘 |
| 用 Python 下第一筆（模擬）委託 | [連線到券商](get-started/connect.md)，接著看[帳戶與委託](get-started/account-and-orders.md) | 15 分鐘 |
| 取得價格並計算技術指標 | [行情資料](get-started/market-data.md) | 10 分鐘 |
| 寫一個策略，用一年的價格測試 | [撰寫策略](get-started/strategy.md)，接著看[回測](get-started/backtesting.md) | 20 分鐘 |
| 像實盤一樣，逐分鐘執行多個 bot | [執行交易引擎](get-started/trading-engine.md) | 15 分鐘 |
| 使用互動式 shell 或網頁介面 | [CJShell 與 FinHub](get-started/shell-and-finhub.md) | 10 分鐘 |
| 排除錯誤 | [疑難排解](get-started/troubleshooting.md) | |

「開始使用」的各頁是一頁接著一頁寫的，第一次看請照順序讀。

## 給已經熟悉 CJTrade 的人

| 要查 | 頁面 |
|---|---|
| 所有指令、選項和連接埠 | [指令](reference/commands.md) |
| 設定檔和環境變數 | [設定與路徑](reference/config.md) |
| 某個類別或函式 | [API 參考](reference/index.md) |

!!! note
    API 還沒穩定，1.0 之前名稱可能會變動。
