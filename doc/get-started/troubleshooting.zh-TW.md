# 疑難排解

常見錯誤、原因與處理方式。

## 連線

??? question "`connect()` 失敗並出現 `Connection refused`"
    用戶端使用的埠上沒有程式在監聽。請確認：

    - `uv run arenaxd` 正在執行，且已印出 `sim env started`。
    - 伺服器和用戶端使用同一個埠（port）。`arenaxd` 在 `demo` 監聽 8801、
      `backtest` 監聽 8802、`paper` 監聽 8803。`AccountClient` 預設連 8801，
      除非設定了 `ARENAX_PORT`；`cjtrade --mode=...` 會選用對應模式的埠。

??? question "啟動伺服器或交易引擎時出現 `Address already in use`"
    另一個執行個體占用了該埠。用 `lsof -nP -iTCP:8801 -sTCP:LISTEN`
    找出它（埠號換成訊息中的埠）並停止。交易引擎也會綁定 5555、5556 和 8898，
    因此同時執行兩個引擎會衝突。

??? question "帳戶又變回 NT$100,000"
    每次啟動 `arenaxd` 都會建立全新的模擬帳戶，帳戶只在伺服器 process 存活期間
    存在。

## 價格

??? question "`get_kbars` 回傳空的 list"
    - 區間晚於 ArenaX 的模擬時鐘 → 改用
      `client.get_market_time()["mock_current_time"]` 之前的日期。
    - 區間內沒有交易日（週末或假日）。
    - 結束日期不包含在內：`start="2025-09-01", end="2025-09-01"`
      是空的區間。
    - 伺服器以 `--data=offline` 執行，而檔案裡沒有該股票代號、K 棒週期或日期的
      資料 → 用 `preload-prices` 預先下載。

??? question "`UnsupportedRequest`"
    該來源完全不提供這個 K 棒週期（例如沒有付費方案的 FinMind 不提供 1 分 K）
    → 用 `Fallback` 在後面串接另一個來源，做法見[行情資料](market-data.md#without-a-broker-free-sources)。

??? question "Yahoo 拿不到較早期間的分 K"
    Yahoo 只保留最近約 30 天的 1 分 K。更早的分 K 需要 Sinopac 或 FinMind
    付費方案。

??? question "`[ERROR] yfinance: ... possibly delisted`"
    Yahoo 在查詢的某一天沒有資料（通常是週末）。程式持續執行時可忽略。

## 委託

??? question "我的委託一直停在 `COMMITTED_WAIT_MATCHING`"
    尚未觸及限價：買單在市價跌到限價時成交，賣單在市價漲到限價時成交。在
    ArenaX 上，模擬時鐘也必須前進，因為委託是以後續的 K 棒撮合。

??? question "我的委託是 `REJECTED`"
    原因在 `result.message`。常見原因：現金不足、賣出股數超過持股、價格離市價
    太遠，或數量不符合整股／零股的規則。

??? question "ArenaX 用比市價高的價格成交我的買單"
    ArenaX 以限價記錄成交 → 限價設在市價附近，成本才貼近實際。詳見
    [帳戶與委託](account-and-orders.md#buy-one-share)。

## 策略與交易引擎

??? question "`strategy-tool check` 說某個名稱未定義"
    該名稱不在策略詞彙中，檔案裡也沒有賦值，通常是拼錯。
    `uv run strategy-tool api` 列出所有可用的名稱。

??? question "我的策略從來不交易"
    - 仍在暖機：20 根 K 棒的指標要滿 20 根 K 棒才有值。查看 bot 狀態中
      `hold(...)` 的原因。
    - 在交易引擎中，bot 的股票代號沒有列在 `--watch-list` 裡。

??? question "交易引擎警告 `broker balance 100000 != requested fund=1000000`"
    ArenaX 帳戶以預設的 NT$100,000 開始 → 以
    `AX_INITIAL_BALANCE=1000000` 啟動 `arenaxd`，使帳戶金額與 `--fund` 一致。

??? question "交易引擎說伺服器沒有重播所需的價格"
    伺服器載入的天數少於重播所需 → 預先下載更長的區間，或以更大的
    `AX_BACKTEST_DURATION_DAYS`（從開始日期起算載入的天數）啟動 `arenaxd`。

## 回報問題

到 <https://github.com/jackiesogi/CJTrade/issues> 開 issue，附上執行的指令和完整
輸出。
