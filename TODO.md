### 重新審視許多需要穩定度的地方
#### backtest full_sim 和 backtest_oneshot 的交易日計算/PnL 計算
1. 交易日到底算幾天（對於使用者端應該是會比較想要只到起始和結束的日期）
2. PnL 計算

### 解決 paper backend / demo backend / backtest backend 三者在 resume_time_progress() 的行為差異
現在會需要 `pause_time_progress()` 的原因主要是因為 cjtrade_system 作為 client 在開始真的 trading 之前
有一些 blocking 的動作，例如 call LLM 先總結一下目前的帳戶水平以及財務健康度並給予投資建議，通常會花 ~10
秒才能拿到輸出；但 `ArenaX_BrokersideServer` 其實以往在 `start_http()` 之後馬上就開始高速重播了，這會導致
client 在等待 LLM 回應的時期漏掉許多取樣點，造成整體 k 線在極端狀況（30,000x 倍速重播）可能會遺失數天的資
料，這會導致整體技術分析指標在計算上是極度不準的；也是因此，backtest mode 現在採取的 workaround 就是在
server 端準備好之後先把時間暫停，等待 client 也準備好要開始作交易的時候，才主動地去 call server 叫它
`resume_time_progress()`。但這其實就會造成一個很詭異的狀況，也就是在實際的狀況中，我們使用者 client 不應該
能夠直接觸及券商後端的伺服器叫它變更某個設定，或是指使後端 server 去完成某相動作。

### 把 poc 加入 app
廣泛測試目前常用的 poc entry point 以及不同的 option，使他們更穩定，確定每一條路線都穩定正常
而且到可以讓使用者開箱即用的程度，並把他們挪動至 `apps` 路徑底下。請注意，現在的 poc script
有的比較像是 wrapper script，如果屬於這種屬性的，請把這個 wrapper 的邏輯整併進實際的 app 本身。

### BaseCommand class 提取
希望可以把 cjtrade shell 的 BaseCommand 那些邏輯加入到 pkg 之中使之可以被重用

### New command requested: `trend`
希望有一個新指令可以被整合到 cjtrade shell 方便操作：顯示近期的走勢（可選擇動態或靜態直接印出）

### Bot deployment engine
希望有一個專門的中央 Daemon 可以用來接收一個一個的 Bot
(裡面包含策略code本身 以及auto enable的觸發條件 例如某個market regime就自動開啟
當然如果先以poc來看先不用做到這步 只需要能夠手動送enable/disable request就好了,
而這個中心的 daemon必須要能夠提供一個介面 可以先從cli開始 先不用restful api server)

### New Developer tools: Easy import
主要就是解決 developer 有時要快速測試某先 API 的時候
需要自己手動寫import一堆東西
可以使用 form schema 的框架先給一個選單來選擇broker以及需要引入的 key file
然後用這個 app 寫成的測試檔案可以被這個 app 統一管理 (進階功能)
更進階的話應該是讓 DEV 用自然語言敘述一下自己要測試的東西（讓 llm 來看需要引入哪些檔案）

# Sinopac API 訂單抽象設計缺陷
Sinopac API 目前這樣封裝在獨立檔案作place_order測試的時候其實非常危險
因為現在 app 裡面（cjtrade_shell）高度仰賴 db 裡面的 CJ_OrderMap 來紀錄原始的 sinopac id
也就是說如果用獨立檔案呼叫 place_order 除非 caller 有自行紀錄要 cancel 掉的 CJ order id
否則程式結束之後這個 id 就消失了（當然使用者還是可以利用 sinopac native api 來撈訂單資料
但這不應該是CJTrade User自己需要去做的 這樣就違反了abstraction的哲理）
應該要有一個方式在 place_order 之後不管使用者有沒有自行紀錄下來 電腦上的 local file 都要有紀錄一份 mapping？
