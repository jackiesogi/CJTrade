# Configuration and paths

Where CJTrade reads its settings from, the settings that exist, and where it
writes files.

## Where settings come from

A setting is a `KEY = value` pair. CJTrade looks for each key in this order
and uses the **first** value it finds:

1. an environment variable (`export API_KEY=...`, or `API_KEY=... command`),
2. a `.env` file in the folder you run from,
3. any `*.cjconf` file in that folder or below it (shallower folders first,
   then alphabetical),
4. `*.cjconf` files in your user settings folder (see [Paths](#paths)),
5. the defaults that ship with CJTrade (`*.cjsys` files).

So a value you `export` always wins over a file, and a file in your project
wins over one in your user folder.

`*.cjconf` files hold your own settings and secrets; keep them out of git
(the repository's `.gitignore` already does). Create a starting one with
`bash scripts/gen_config.sh arenax` or `... sinopac`.

!!! tip "Which file did a value come from?"
    `cjtrade.pkgs.config.config_loader.describe_sources()` prints every
    setting with the file or variable it came from.

## Broker settings (`*.cjconf`)

| Key | Used by | Meaning |
|---|---|---|
| `API_KEY` | ArenaX, Sinopac | ArenaX: `testkey123`. Sinopac: your API key |
| `SECRET_KEY` | Sinopac | your API secret |
| `CA_CERT_PATH` | Sinopac | path to your `Sinopac.pfx` certificate |
| `CA_PASSWORD` | Sinopac | the certificate's password |
| `SIMULATION` | Sinopac | `y` for Sinopac's sandbox, `n` for your **real account** (the generated file says `n`) |
| `LLM_MODEL`, `LLM_API_KEY`, `GEMINI_API_KEY` | LLM clients, CJShell `llm` | which model and its key |
| `FINMIND_TOKEN` | FinMind price source | optional; raises the request limit |

## CJTrade-wide variables

| Variable | Meaning |
|---|---|
| `CJTRADE_HOME` | put every folder below under this one path |
| `CJTRADE_OFFLINE=1` | every network price source fails instead of connecting |
| `CJTRADE_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, ... |
| `ARENAX_PORT` | the port `AccountClient` connects to on ArenaX (default 8801) |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | required to start `arenaxd --backend=real` |

## ArenaX server settings (`AX_*`) {#arenax-server-settings}

Each backend has defaults in `src/cjtrade/apps/ArenaX/configs/<backend>.cjsys`;
set a variable to override one.

| Variable | Default (demo) | Meaning |
|---|---|---|
| `AX_HOST_PORT` | 8801 | port (backtest 8802, paper 8803, real 8888) |
| `AX_DATA_SOURCES` | `yfinance` | price sources, as `--data` |
| `AX_PRICE_DB_PATH` | shared cache | price file, as `--price-db` |
| `AX_INITIAL_BALANCE` | 100000 | starting cash of a fresh account |
| `AX_STATE_FILE` | | an account snapshot to resume from instead of starting fresh |
| `AX_BACKTEST_DURATION_DAYS` | 11 (backtest 300) | how many days of prices to load from the start date |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 | market seconds per real second |
| `AX_SKIP_NON_TRADING_HOURS` | `y` | jump over nights and weekends |
| `AX_COMMISSION_DISCOUNT` | 1.0 | 0.6 is a 六折 discount |
| `AX_SLIPPAGE_MODEL`, `AX_SLIPPAGE_PCT` | `none`, 0.0005 | slippage model and size (not yet applied to ArenaX fills) |

## FinHub settings (`FINHUB_*`)

See the [FinHub README](https://github.com/jackiesogi/CJTrade/blob/master/src/cjtrade/apps/FinHub/README.md#settings).

## Paths {#paths}

| Folder | Holds | macOS | Linux |
|---|---|---|---|
| config | `*.cjconf`, `finhub.env` | `~/Library/Application Support/cjtrade` | `~/.config/cjtrade` |
| data | reports, account snapshots, FinHub's database | `~/Library/Application Support/cjtrade` | `~/.local/share/cjtrade` |
| cache | the price cache `arenax_price.db` | `~/Library/Caches/cjtrade` | `~/.cache/cjtrade` |
| state, logs | runtime state, log files | `~/Library/Application Support/cjtrade`, `~/Library/Logs/cjtrade` | `~/.local/state/cjtrade`, `~/.local/state/cjtrade/log` |

With `CJTRADE_HOME=/some/path`, they become `/some/path/config`,
`/some/path/data`, `/some/path/cache`, `/some/path/state` and
`/some/path/logs`. `arenaxd` prints the folders it uses when it starts.

## API

!!! warning
    `load_supported_config_files()` writes into `os.environ` for the whole
    process (first source wins), and the `paths` helpers create directories
    the first time they are asked.

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
