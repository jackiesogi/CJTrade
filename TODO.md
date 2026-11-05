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

# ArenaXMiddleWare 每次請求都會開一條新的 HTTP connection
`src/cjtrade/pkgs/brokers/arenax/arenax_middleware.py` 的 `_get()`/`_post()` 是用
`requests.get(url, ...)` / `requests.post(url, ...)` 這種 module-level 便利函式打 API，
沒有共用 `requests.Session()`。這兩個函式的實作本質上是
`with sessions.Session() as session: return session.request(...)`，
所以每呼叫一次就會建立一個全新的 Session、打完立刻關掉，底層 TCP connection 完全沒有
keep-alive、沒有被 pool 重用（在 poc/trading_engine 測試 EventHub 的 `_snapshot` 時，
從 log 可以看到 urllib3 對每一次 `/market/snapshot` 查詢都印出
"Starting new HTTP connection"，證實了這點）。

現在是打 `http://localhost:8802`（無 TLS、本機），成本還不明顯，但之後 symbol 數量變多、
polling 頻率變高，或 server 換到真的網路環境時，這個開銷會被放大。

修法：在 `ArenaXMiddleWare.__init__` 存一個 `self._session = requests.Session()`，
`_get`/`_post` 改成呼叫 `self._session.get(...)/self._session.post(...)`，對外介面不變，
純粹讓底層連線可以重用。這是共用的 broker 程式碼，會影響整個 app 用 ArenaX 的地方，
不只是 poc/trading_engine，所以需要另外評估影響範圍再動手。

### Config provenance（效法 `git config --show-origin`）
目前 `config_loader.load_supported_config_files()` 把每個檔案 `load_dotenv()` 進
`os.environ`，**provenance 在那一刻就丟掉了**。之後 `os.environ.get('API_KEY')` 無法
知道這個值是哪個檔案設的、有沒有被其他檔案覆蓋過。config 一多就很難 debug。

希望做到像 git 那樣可以問：
```sh
cjtrade config --show-origin --show-scope CJSYS_BACKTEST_PLAYBACK_SPEED
#   local   ./backtest.cjconf:12   30000.0      ← 生效
#   global  ~/.../cjtrade/system.cjconf:8  1200.0
#   system  <package>/configs/backtest.cjsys:41  1200.0
```

#### 兩種實作路線
- **(a) 包一層 registry**：自己 parse 每個 `.cjconf` / `.cjsys`，記錄
  `{key: [(value, source_file, line_no, scope), ...]}`，然後才寫進 environ。
  可以完整回答「這個 key 有幾個來源、誰贏了、被誰蓋掉」。比較貼近
  `git config --get-all` 的效果。
- **(b) 只記錄最後贏家**：每次 `load_dotenv` 前後 diff `os.environ`，把新增／變更的
  key 歸給該檔案。改動極小，但看不到被覆蓋掉的那些。

傾向 (a)。

#### 連帶要解決的：scope 階層
現在 `load_dotenv(override=False)` 是**先載入的贏**，而 git 是**後面的 scope 贏**
（local > global > system）。兩者方向相反。而且原本 `SUPPORTED_CONFIG_PATHS` 只有
`.env` 和 CWD，沒有 user 層級（已補上 `paths.config_dir()`，但順序仍是「先載入的贏」
以維持相容）。

希望收斂成跟 git 一致的階層，後者覆蓋前者：
```
system   套件內建預設（<package>/apps/*/configs/*.cjsys）
  ↓
global   paths.config_dir()/*.cjconf          使用者層級
  ↓
local    ./*.cjconf、./.env                   專案層級
  ↓
env      直接設定的環境變數                    最高
```

注意這會**反轉現有的優先序**，所以要一起處理：
1. 把 `override=False` 改成按 scope 順序載入 + `override=True`
2. 確認現有的 `.cjsys` 預設值不會蓋掉使用者的 `.cjconf`
3. `config_loader.py:_default_config_paths()` 的 docstring 有記錄這個已知落差

#### 更該優先修的：CWD 內多檔之間順序未定義
實測目前的優先序（`override=False` → 最先設定某 key 的來源贏）：
```
1 已存在的環境變數   ← 最高，打敗所有檔案
2 ./.env
3 ./**/*.cjconf      ← 這一層內部的順序是「未定義」的
4 <user config>/*.cjconf
5 套件內建 *.cjsys   ← 最低（load_cjsys 在 load_cjconf 之後跑）
```

第 3 層的問題：`load_supported_config_files()` 對 CWD 用 `p.rglob(pattern)`，而
`rglob` 的回傳順序是檔案系統的 `readdir` 順序 —— 不是字母序也不是深度序。實測：
```
root.cjconf
portoverride.cjconf
_backup.cjconf
sub/nested.cjconf
```
所以 tree 裡有兩個 `.cjconf` 設同一個 key 時，**誰贏跨機器可能不同**，甚至同一台機器
上檔案重建後就變了。

這比「優先序方向跟 git 相反」更嚴重 —— 後者只是不直覺，前者是同一份 repo 在不同
機器上行為不同。至少要先 `sorted(p.rglob(...))` 讓它可預測，理想上淺層優先於深層
（跟 git 的 local 比 parent 強一致）。

#### 另外
`CJTradeConfiguration` 這個空 class 和它上面那條
「Implement a hierarchical configuration structure (e.g. `simulation.playback_speed`)」
的 TODO 應該一起做掉 —— 階層式 key 和 provenance 是同一件事的兩面。
