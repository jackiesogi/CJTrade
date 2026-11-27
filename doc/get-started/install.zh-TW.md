# 安裝

安裝與驗證約需五分鐘。

## 需求

| 工具 | 用途 | 確認方式 |
|---|---|---|
| Python 3.12 以上 | CJTrade 是 Python 套件 | `python3 --version` 顯示 `Python 3.12.x` 或更新版本 |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 安裝相依套件，並在專案環境中執行指令 | `uv --version` |
| git | 取得原始碼 | `git --version` |

支援 Linux 和 macOS，未在 Windows 上測試。

## 安裝方式

=== "從原始碼安裝（建議初次使用）"

    包含函式庫、所有命令列工具、範例程式和測試。

    ```sh
    git clone https://github.com/jackiesogi/CJTrade
    cd CJTrade
    uv sync
    ```

    `uv sync` 會在 `CJTrade/.venv` 建立環境並安裝所有相依套件（包含全部選用套件），不會動到系統的 Python。

    本文件中的指令都請在 **`CJTrade` 資料夾內**執行，並加上 `uv run` 前綴；`uv run python` 就是已安裝 CJTrade 的直譯器。

=== "用 pip 安裝"

    包含函式庫和命令列工具，但不含 `scripts/`、`poc/` 和 `tests/` 底下的範例程式。

    ```sh
    pip install cjtrade
    ```

    核心套件包含 ArenaX（模擬券商）、回測、shell 和報表，其餘功能為選用套件（extra）：

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

    以 pip 安裝時，本文件中的指令都要去掉 `uv run` 前綴：`uv run arenaxd` 改成 `arenaxd`。

## 驗證安裝

```sh
uv run strategy-tool templates
```

預期輸出（一行 JSON，這裡有省略）：

```text
{"templates": [{"kind": "bb", "label": "Bollinger mean reversion", ...}, {"kind": "dca", ...}, ...]}
```

??? question "出現 `command not found` 或 `No module named cjtrade`"
    - 從原始碼安裝：須在 `CJTrade` 資料夾內執行。
    - 指令前須加上 `uv run`。
    - 以 pip 安裝：所用的 `pip` 必須屬於正在執行的 Python（改用 `python3 -m pip install cjtrade` 可避免混用）。

## 檔案位置

CJTrade 不會寫入目前的工作目錄。報表、價格快取和帳戶快照都放在使用者目錄下：

| 內容 | macOS | Linux |
|---|---|---|
| 設定 | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| 報表、帳戶快照 | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| 價格快取 | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |

若要把所有檔案集中在同一個目錄，請設定 `CJTRADE_HOME`：

```sh
export CJTRADE_HOME=~/cjtrade-data
```

下一步：[基本概念](concepts.md)。
