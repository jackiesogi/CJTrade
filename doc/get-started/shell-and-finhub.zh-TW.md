# CJShell 與 FinHub

有兩個工具讓你不用寫程式就能使用 CJTrade：**CJShell** 是操作帳戶的命令列，
**FinHub** 是操作交易引擎的網頁。

## CJShell {#cjshell}

CJShell 會連線到券商，讓你輸入 `balance`、`buy` 這類指令。想查看帳戶或手動下一筆
委託，用它最快。

### 第一次使用前的設定

CJShell 從設定檔讀取連線設定。先為 ArenaX 建立一個：

```sh
bash scripts/gen_config.sh arenax
```

這會在目前的資料夾寫出 `arenax_system.cjconf`，其中 `API_KEY = testkey123` 已經
填好，其他欄位留空。只有要用 `llm` 指令或永豐金證券 Sinopac 時，才需要填寫其他欄位。

### 執行一個指令，或連續執行多個

先讓 ArenaX 執行起來（見[連線到券商](connect.md)），在選項後面接上指令，就會只執行
這一次：

```sh
uv run cjshell --broker=arenax balance
```

預期輸出：

```text
[INFO][...] config: loaded cfg file .../arenax_system.cjconf
[INFO][...] brokers.arenax: connected
Executing: balance
Account Balance: 97562.6
[INFO][...] brokers.arenax: disconnected
```

不接指令的話，會進入互動式提示字元，可以一個接一個輸入指令；輸入 `help` 列出所有
指令，輸入 `exit` 離開：

```sh
uv run cjshell --broker=arenax
```

最常用的指令：

| 指令 | 作用 |
|---|---|
| `balance` | 顯示現金 |
| `lspos` | 列出持股及各自的損益 |
| `lsodr [n]` | 列出最近的委託及其狀態 |
| `buy <symbol> <price> <quantity>` | 下限價買單（零股，所以數量單位是股） |
| `sell <symbol> <price> <quantity>` | 下限價賣單 |
| `cancel` | 取消所有未成交的委託 |
| `ohlcv <symbol>` | 最新報價 |
| `bidask <symbol>` | 最佳買賣價 |
| `help [command]` | 列出所有指令，或顯示單一指令的詳細說明 |

例如買進一股 2330 之後執行 `lspos`：

```text
Executing: lspos
  symbol  quantity  avg_cost  current_price  market_value  unrealized_pnl
0   2330         1    2417.4         2360.0        2360.0           -57.4
Total Cost: 2,417.400
Market Value: 2,360.000
Total Unrealized PnL: -57.400 (-2.37%)
```

!!! danger "在 Sinopac 上，CJShell 會直接下真的委託，不會再確認"
    `uv run cjshell --broker=sinopac` 使用 `sinopac_system.cjconf`（用
    `bash scripts/gen_config.sh sinopac` 建立，再填入你的金鑰）。在這裡輸入
    `buy` 就是真的委託，會立刻送出，不會再問你一次。產生出來的檔案寫的是
    `SIMULATION = n`，也就是你的正式帳戶；改成 `SIMULATION = y` 才會使用永豐的
    沙盒（模擬環境）。

## FinHub {#finhub}

FinHub 是交易引擎的網頁介面。你在表單裡選好 bot、股票代號和日期，啟動執行，
就能在執行過程中看到每個 bot 的決策、委託和損益。每次執行都會保留下來，之後可以
互相比較。

```sh
uv run finhub
```

接著打開 <http://127.0.0.1:8000>，註冊一個使用者（資料只存在你的電腦上）並登入。
FinHub 會自己啟動 ArenaX 伺服器和交易引擎，不需要事先執行其他程式。

FinHub 只在你自己的電腦上監聽（`127.0.0.1`）。要從其他機器開啟，請用 SSH 轉送埠（port）：
`ssh -L 8000:127.0.0.1:8000 <host>`。

!!! note "沒有執行中的工作時出現的警告"
    沒有執行中的工作時，FinHub 的日誌每隔幾秒就會印出
    `broker unreachable` 和 `engine status API ... All connection attempts
    failed`。這不是錯誤：只是在你啟動執行之前，還沒有券商或引擎可以查詢。

相關設定請見
[FinHub README](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/apps/FinHub/README.md)。

下一步：[疑難排解](troubleshooting.md)，或到[指令](../reference/commands.md)查詢。
