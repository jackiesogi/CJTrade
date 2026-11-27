# Configuration and paths

Setting sources and precedence, the available settings, and the
directories CJTrade writes to.

## Where settings come from

Settings are `KEY = value` pairs. Each key is resolved from these sources
in order; the **first** value found wins:

1. an environment variable (`export API_KEY=...`, or `API_KEY=... command`),
2. a `.env` file in the working directory,
3. any `*.cjconf` file in the working directory or below it (shallower
   directories first, then alphabetical),
4. `*.cjconf` files in the user config directory (see [Paths](#paths)),
5. the defaults shipped with CJTrade (`*.cjsys` files).

An exported variable therefore overrides any file, and a project file
overrides one in the user config directory.

`*.cjconf` files hold your settings and secrets; keep them out of git (the
repository's `.gitignore` already excludes them). Generate a starting file
with `bash scripts/gen_config.sh arenax` or `... sinopac`.

!!! tip "Which file did a value come from?"
    `cjtrade.pkgs.config.config_loader.describe_sources()` prints every
    setting with its source file or variable.

## Broker settings (`*.cjconf`)

| Key | Used by | Meaning |
|---|---|---|
| `API_KEY` | ArenaX | `testkey123`, the key every ArenaX server accepts |
| `SINOPAC_API_KEY` | Sinopac | your API key |
| `SINOPAC_SECRET_KEY` | Sinopac | your API secret |
| `SINOPAC_CA_CERT_PATH` | Sinopac | path to your `Sinopac.pfx` certificate |
| `SINOPAC_CA_PASSWORD` | Sinopac | the certificate's password |
| `SINOPAC_SIMULATION` | Sinopac | `y` for Sinopac's sandbox, `n` for your **real account** (the generated file says `n`) |
| `FUBON_PERSONAL_ID` | Fubon | the account holder's ID number (身分證字號) |
| `FUBON_API_KEY` or `FUBON_PASSWORD` | Fubon | API-key login, or password login |
| `FUBON_CERT_PATH`, `FUBON_CERT_PASSWORD` | Fubon | the `.pfx` certificate and its password |
| `FUBON_ACCOUNT` | Fubon | optional: the account number to trade when the login returns several |
| `YUANTA_ACCOUNT` | Yuanta | `S` + branch (4) + account (7), e.g. `S98875005091` |
| `YUANTA_PASSWORD` | Yuanta | the account's electronic password |
| `YUANTA_CERT_PATH`, `YUANTA_CERT_PASSWORD` | Yuanta | the `.pfx` certificate and its password; required on Linux and macOS |
| `YUANTA_DLL_DIR` | Yuanta | the folder with Yuanta's Spark API files (`YuantaSparkAPI.dll`, ...) |
| `YUANTA_ENVIRONMENT` | Yuanta | `UAT` (Yuanta's test environment, the default) or `PROD` (your **real account**) |
| `LLM_MODEL`, `LLM_API_KEY`, `GEMINI_API_KEY` | LLM clients, CJShell `llm` | which model and its key |
| `FINMIND_TOKEN` | FinMind price source | optional; raises the request limit |

`bash scripts/gen_config.sh sinopac`, `... fubon` and `... yuanta` write
files with these keys. `cjtrade.pkgs.config.broker_settings` turns them into `AccountClient`
arguments: `AccountClient(BrokerType.FUBON, **fubon_config())`.

!!! note "Old Sinopac names"
    Sinopac's keys were unprefixed before (`API_KEY`, `SECRET_KEY`,
    `CA_CERT_PATH`, `CA_PASSWORD`, `SIMULATION`). They are still read when the
    `SINOPAC_` name is unset, with a warning. If either `SINOPAC_SIMULATION`
    or `SIMULATION` is `y`, the sandbox is used.

## CJTrade-wide variables

| Variable | Meaning |
|---|---|
| `CJTRADE_HOME` | root for every directory in the Paths table below |
| `CJTRADE_OFFLINE=1` | network price sources fail instead of connecting |
| `CJTRADE_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, ... |
| `ARENAX_PORT` | the port `AccountClient` connects to on ArenaX (default 8801) |
| `I_UNDERSTAND_REAL_TRADING_RISKS=y` | required to start `arenaxd --backend=real` |

## ArenaX server settings (`AX_*`) {#arenax-server-settings}

Per-backend defaults live in `src/cjtrade/apps/ArenaX/configs/<backend>.cjsys`;
set the variable to override.

| Variable | Default (demo) | Meaning |
|---|---|---|
| `AX_HOST_PORT` | 8801 | port (backtest 8802, paper 8803, real 8888) |
| `AX_DATA_SOURCES` | `yfinance` | price sources, as `--data` |
| `AX_PRICE_DB_PATH` | shared cache | price file, as `--price-db` |
| `AX_INITIAL_BALANCE` | 100000 | starting cash of a fresh account |
| `AX_STATE_FILE` | | account snapshot to resume from instead of a fresh account |
| `AX_BACKTEST_DURATION_DAYS` | 11 (backtest 300) | days of prices to load from the start date |
| `AX_BACKTEST_PLAYBACK_SPEED` | 120 | market seconds per real second |
| `AX_SKIP_NON_TRADING_HOURS` | `y` | jump over nights and weekends |
| `AX_COMMISSION_DISCOUNT` | 1.0 | commission multiplier; 0.6 is a 六折 discount |
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
`/some/path/logs`. `arenaxd` prints the directories it uses at startup.

## API

!!! warning
    `load_supported_config_files()` writes into `os.environ` for the whole
    process (first source wins), and the `paths` helpers create directories
    the first time they are asked.

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
