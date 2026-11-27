# 安裝

這一頁帶你把 CJTrade 裝到電腦上，並確認它能正常運作。大約需要五分鐘。

## 需要準備的工具

| 工具 | 用途 | 確認方式 |
|---|---|---|
| Python 3.12 以上 | CJTrade 是一個 Python 套件 | `python3 --version` 顯示 `Python 3.12.x` 或更新版本 |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 安裝 Python 套件，並在專案環境中執行指令 | `uv --version` |
| git | 下載原始碼 | `git --version` |

CJTrade 可在 Linux 和 macOS 上執行，沒有在 Windows 上測試過。

## 兩種安裝方式

=== "從原始碼安裝（建議新手使用）"

    你會拿到函式庫、所有命令列工具、範例程式和測試。

    ```sh
    git clone https://github.com/jackiesogi/CJTrade
    cd CJTrade
    uv sync
    ```

    - `git clone` 會把程式碼下載到名為 `CJTrade` 的資料夾。
    - `uv sync` 會在 `CJTrade/.venv` 建立一個專屬的 Python 環境，並把 CJTrade 需要的東西（包含所有選用套件）都裝進去。系統原本的 Python 不會被動到。

    之後請在 **`CJTrade` 資料夾裡**執行指令，並在指令前面加上 `uv run`。`uv run` 會在那個專屬環境中執行指令，所以 `uv run python` 就是已經裝好 CJTrade 的 Python。

=== "用 pip 安裝套件"

    你會拿到函式庫和命令列工具，但沒有 `scripts/`、`poc/` 和 `tests/` 底下的範例程式。

    ```sh
    pip install cjtrade
    ```

    核心套件包含模擬券商、回測、shell 和報表。其他功能是*選用套件（extra）*：需要時寫在方括號裡一起安裝。

    ```sh
    pip install 'cjtrade[sinopac,finhub]'
    ```

    | 選用套件 | 加裝的內容 | 用途 |
    |---|---|---|
    | `sinopac` | `shioaji` SDK | 在 Sinopac 交易，以及從 Sinopac 讀取價格 |
    | `finhub` | FastAPI 等相關套件 | FinHub 網頁介面 |
    | `llm` | Gemini 和 Azure OpenAI 用戶端 | shell 的 `llm` 指令、LLM 輔助功能 |
    | `news` | NewsAPI 用戶端 | NewsAPI 新聞來源 |
    | `all` | 以上全部 | |

    用這種方式安裝時，本文件中的指令都要拿掉 `uv run`：`uv run arenaxd` 改成 `arenaxd`。

## 確認安裝成功

請其中一個工具印出它的說明：

```sh
uv run strategy-tool templates
```

預期輸出（一行 JSON，這裡有省略）：

```text
{"templates": [{"kind": "bb", "label": "Bollinger mean reversion", ...}, {"kind": "dca", ...}, ...]}
```

看到這段輸出，就代表 CJTrade 已經裝好了。

??? question "出現 `command not found` 或 `No module named cjtrade`"
    - 確認你在 `CJTrade` 資料夾裡（從原始碼安裝時）。
    - 確認指令前面有加 `uv run`。
    - 如果是用 pip 安裝，確認你用的 `pip` 屬於你正在執行的那個 Python（改用 `python3 -m pip install cjtrade` 就不會搞混）。

## CJTrade 把檔案放在哪裡

CJTrade 不會把檔案寫進你執行它的資料夾。報表、價格快取和帳戶快照都會放在你的使用者資料夾：

| 內容 | macOS | Linux |
|---|---|---|
| 設定 | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| 報表、帳戶快照 | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| 價格快取 | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |

如果想把所有東西放在同一個資料夾，請設定 `CJTRADE_HOME`：

```sh
export CJTRADE_HOME=~/cjtrade-data
```

下一步：[基本概念](concepts.md)。
