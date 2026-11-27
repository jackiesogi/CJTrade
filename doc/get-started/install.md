# Install

This page gets CJTrade onto your computer and checks that it works. It takes
about five minutes.

## What you need

| Tool | Why | Check you have it |
|---|---|---|
| Python 3.12 or newer | CJTrade is a Python package | `python3 --version` prints `Python 3.12.x` or higher |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | installs Python packages and runs commands in the project's environment | `uv --version` |
| git | downloads the source code | `git --version` |

CJTrade runs on Linux and macOS. It is not tested on Windows.

## Two ways to install

=== "From the source code (recommended to start)"

    You get the library, every command-line tool, the example scripts and
    the tests.

    ```sh
    git clone https://github.com/jackiesogi/CJTrade
    cd CJTrade
    uv sync
    ```

    - `git clone` downloads the code into a folder called `CJTrade`.
    - `uv sync` creates a private Python environment in `CJTrade/.venv` and
      installs everything CJTrade needs into it, including every optional
      part. Your system Python is not touched.

    From now on, run commands **inside the `CJTrade` folder** and put
    `uv run` in front of them. `uv run` runs a command inside that private
    environment, so `uv run python` is the Python that has CJTrade installed.

=== "As a package with pip"

    You get the library and the command-line tools, but not the example
    scripts under `scripts/`, `poc/` and `tests/`.

    ```sh
    pip install cjtrade
    ```

    The core covers the pretend broker, backtesting, the shell and reports.
    Other parts are *extras*: add them in brackets when you need them.

    ```sh
    pip install 'cjtrade[sinopac,finhub]'
    ```

    | Extra | Adds | You need it for |
    |---|---|---|
    | `sinopac` | the `shioaji` SDK | trading on Sinopac, and reading prices from Sinopac |
    | `finhub` | FastAPI and friends | the FinHub web UI |
    | `llm` | Gemini and Azure OpenAI clients | the shell's `llm` command, LLM helpers |
    | `news` | NewsAPI client | the NewsAPI news source |
    | `all` | all of the above | |

    In this case, drop the `uv run` from the commands in these pages:
    `uv run arenaxd` becomes `arenaxd`.

## Check that it works

Ask one of the tools for its help text:

```sh
uv run strategy-tool templates
```

Expected output (one line of JSON, shortened here):

```text
{"templates": [{"kind": "bb", "label": "Bollinger mean reversion", ...}, {"kind": "dca", ...}, ...]}
```

If you see that, CJTrade is installed.

??? question "It says `command not found` or `No module named cjtrade`"
    - Make sure you are inside the `CJTrade` folder (from-source install).
    - Make sure you typed `uv run` in front of the command.
    - If you installed with pip, make sure the `pip` you used belongs to the
      Python you are running (`python3 -m pip install cjtrade` avoids the
      mix-up).

## Where CJTrade keeps its files

CJTrade never writes into the folder you run it from. Reports, the price
cache and account snapshots go to your user folders:

| What | macOS | Linux |
|---|---|---|
| Settings | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| Reports, account snapshots | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| Price cache | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |

To keep everything in one folder instead, set `CJTRADE_HOME`:

```sh
export CJTRADE_HOME=~/cjtrade-data
```

Next: [Key ideas](concepts.md).
