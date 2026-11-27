# Install

Installing and verifying takes about five minutes.

## Requirements

| Tool | Purpose | Check |
|---|---|---|
| Python 3.12 or newer | CJTrade is a Python package | `python3 --version` prints `Python 3.12.x` or higher |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | installs dependencies and runs commands in the project environment | `uv --version` |
| git | clones the source | `git --version` |

Supported on Linux and macOS. Not tested on Windows.

## Install options

=== "From source (recommended to start)"

    Includes the library, every command-line tool, the example scripts and
    the tests.

    ```sh
    git clone https://github.com/jackiesogi/CJTrade
    cd CJTrade
    uv sync
    ```

    `uv sync` creates the environment in `CJTrade/.venv` and installs all
    dependencies, including every optional extra. The system Python is left
    untouched.

    Run all commands in these pages **from the `CJTrade` folder**, prefixed
    with `uv run`; `uv run python` is the interpreter with CJTrade installed.

=== "With pip"

    Includes the library and the command-line tools, but not the example
    scripts under `scripts/`, `poc/` and `tests/`.

    ```sh
    pip install cjtrade
    ```

    The core covers ArenaX (the simulated broker), backtesting, the shell
    and reports. Everything else is an extra:

    ```sh
    pip install 'cjtrade[sinopac,fubon,finhub]'
    ```

    | Extra | Adds | Required for |
    |---|---|---|
    | `sinopac` | the `shioaji` SDK | trading on Sinopac, and reading prices from Sinopac |
    | `fubon` | the `fubon-neo` SDK | trading on Fubon |
    | `yuanta` | `pythonnet` (plus .NET 8 and Yuanta's Spark API files) | trading on Yuanta |
    | `finhub` | FastAPI and friends | the FinHub web UI |
    | `llm` | Gemini and Azure OpenAI clients | the shell's `llm` command, LLM helpers |
    | `news` | NewsAPI client | the NewsAPI news source |
    | `all` | all of the above | |

    With a pip install, drop the `uv run` prefix from the commands in these
    pages: `uv run arenaxd` becomes `arenaxd`.

## Verify

```sh
uv run strategy-tool templates
```

Expected output (one line of JSON, shortened here):

```text
{"templates": [{"kind": "bb", "label": "Bollinger mean reversion", ...}, {"kind": "dca", ...}, ...]}
```

??? question "It says `command not found` or `No module named cjtrade`"
    - From-source install: run from inside the `CJTrade` folder.
    - Prefix the command with `uv run`.
    - pip install: the `pip` you used must belong to the Python you are
      running (`python3 -m pip install cjtrade` avoids the mix-up).

## File locations

CJTrade never writes into the working directory. Reports, the price cache
and account snapshots go to per-user directories:

| What | macOS | Linux |
|---|---|---|
| Settings | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| Reports, account snapshots | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| Price cache | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |

To keep everything under one directory, set `CJTRADE_HOME`:

```sh
export CJTRADE_HOME=~/cjtrade-data
```

Next: [Key ideas](concepts.md).
