# 疑難排解

常見問題、發生原因，以及處理方式。

## 連線

??? question "`connect()` 失敗並出現 `Connection refused`"
    用戶端連線的位置沒有任何程式在監聽。請確認：

    - 另一個終端機裡正在執行 `uv run arenaxd`，而且已經印出
      `sim env started`；
    - 伺服器和用戶端使用同一個埠（port）。`arenaxd` 在 `demo` 用 8801、
      `backtest` 用 8802、`paper` 用 8803；`AccountClient` 預設連 8801，除非你設定了
      `ARENAX_PORT`；`cjtrade --mode=...` 則會自動選用對應模式的埠。

??? question "啟動伺服器或交易引擎時出現 `Address already in use`"
    已經有另一份程式在執行。用
    `lsof -nP -iTCP:8801 -sTCP:LISTEN` 找出它（埠號換成訊息中的那個），再停止該
    程式。交易引擎也會使用 5555、5556 和 8898 埠，所以同時執行兩個引擎會互相衝突。

??? question "帳戶又變回 NT$100,000"
    每次啟動 `arenaxd` 都會開一個全新的模擬帳戶。只要伺服器持續執行，帳戶就會一直
    保留。

## 價格

??? question "`get_kbars` 回傳空的 list"
    - 查詢的區間在 ArenaX 模擬時鐘的未來。請使用
      `client.get_market_time()["mock_current_time"]` 之前的日期。
    - 區間內沒有交易：週末或假日。
    - 結束日期不包含在內：`start="2025-09-01", end="2025-09-01"`
      是空的區間。
    - 伺服器以 `--data=offline` 執行，而檔案裡沒有該股票代號、K 棒週期或日期的資料。
      請用 `preload-prices` 預先下載。

??? question "`UnsupportedRequest`"
    該來源完全不提供這個 K 棒週期，例如沒有付費方案時，FinMind 不提供 1 分 K。
    請用 `Fallback` 在後面接上另一個來源，做法見[行情資料](market-data.md#without-a-broker-free-sources)。

??? question "Yahoo 拿不到較早期間的分 K"
    Yahoo 只保留最近大約 30 天的 1 分 K。更早的分 K 需要用 Sinopac，或 FinMind
    付費方案。

??? question "`[ERROR] yfinance: ... possibly delisted`"
    Yahoo 在查詢的某一天沒有資料（通常是週末）。只要程式繼續執行，就可以忽略這則
    訊息。

## 委託

??? question "我的委託一直停在 `COMMITTED_WAIT_MATCHING`"
    價格還沒到。買單要等市價跌到你的限價才會成交，賣單則要等市價漲到限價。在
    ArenaX 上，時間也必須往前走：委託是拿接下來的 K 棒來撮合的。

??? question "我的委託是 `REJECTED`"
    請看 `result.message`。常見原因有：現金不足、賣出的股數超過持股、價格離市價
    太遠，或數量不符合整股／零股的規則。

??? question "ArenaX 用比市價高的價格成交我的買單"
    ArenaX 是以你的限價記錄成交。想讓成本貼近實際，請把限價設在市價附近。詳見
    [帳戶與委託](account-and-orders.md#buy-one-share)。

## 策略與交易引擎

??? question "`strategy-tool check` 說某個名稱未定義"
    這個名稱既不在策略可用的詞彙裡，也沒有在你的檔案中設定，通常是打錯字。
    `uv run strategy-tool api` 會列出所有可以使用的名稱。

??? question "我的策略從來不交易"
    - 可能還在暖機：20 根 K 棒的指標，要等滿 20 根 K 棒才會有值。請查看 bot 狀態中
      `hold(...)` 的原因。
    - 在交易引擎中，bot 的股票代號必須列在 `--watch-list` 裡。

??? question "交易引擎警告 `broker balance 100000 != requested fund=1000000`"
    ArenaX 帳戶是以預設的 NT$100,000 開始。請用
    `AX_INITIAL_BALANCE=1000000` 啟動 `arenaxd`，讓帳戶金額和 `--fund` 一致。

??? question "交易引擎說伺服器沒有重播所需的價格"
    伺服器載入的天數比你要重播的天數少。請預先下載更長的區間，或用更大的
    `AX_BACKTEST_DURATION_DAYS`（從開始日期起算要載入的天數）啟動 `arenaxd`。

## 還是無法解決

請到 <https://github.com/jackiesogi/CJTrade/issues> 開一個 issue，附上你執行的
指令和完整的輸出。
