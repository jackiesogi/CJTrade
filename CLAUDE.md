# CLAUDE.md

Orientation for an AI agent working in this repo. Read this before touching code.

---

## 1. What this project is

CJTrade is a trading-system development framework for TWSE (台股). You write a
strategy against the CJTrade API and run it against any supported broker
(證券商) without changing the strategy.

Two halves:

| | |
|---|---|
| `src/cjtrade/pkgs/` | The SDK. Brokers, models, strategies, analytics, DB, LLM, charts, forms. |
| `src/cjtrade/apps/` | Applications built on the SDK. CJTrade (the trading app), ArenaX, CJShell, FinHub, CJEdit, CJNews. |

Brokers: **Sinopac** (永豐金, real) and **ArenaX** (built-in simulated exchange).
Cathay / Yuanta are stubs.

**ArenaX is the important one.** It is a full broker-side server (Flask) with
its own clock, order book, matching loop and account state, so backtest /
paper / demo all speak the same HTTP API as a real broker. That is why
`AccountClient` code is identical across brokers.

ArenaX has four backends (`--backend=`):

| backend | default prices (`--data`) | orders go to | port |
|---|---|---|---|
| `demo` | `yfinance` | ArenaX matching | 8801 |
| `backtest` | `sinopac,yfinance` (historical replay) | ArenaX matching | 8802 |
| `paper` | `sinopac` (live) | ArenaX matching | 8803 |
| `real` | `sinopac` (live) | **real Sinopac** — needs `I_UNDERSTAND_REAL_TRADING_RISKS=y` | 8888 |

> A Sinopac price source **logs in to the real Sinopac account**. It never
> places orders (only `real_backend.py` overrides `place_order`), but it burns
> API quota. Choose sources with `--data` / `AX_DATA_SOURCES`:
> `--data=finmind,yfinance` needs no account, and `--data=offline
> --price-db=FILE` reads only a file filled by `preload-prices`.

---

## 2. Commands

```sh
uv sync                                   # install
source .venv/bin/activate

uv run pytest                            # unit + integration (arenax/ skips without arenaxd; cjtrade/ starts its own)
uv run pytest tests/unit/ -q              # ~1,400 tests, ~65s, no network
bash tests/run_broker_stability_tests.sh --broker=arenax   # starts arenaxd :8801, runs tests/integration/arenax
uv run pytest tests/integration/cjtrade  # engine end to end, offline (~45s, starts arenaxd :8802)
uv run arenaxd --backend=demo             # ArenaX broker-side server (demo :8801, backtest :8802)
uv run cjshell --broker=arenax            # interactive shell (CJShell)
uv run cjtrade --broker=arenax --mode=backtest  # the trading app (engine + bots)
uv run finhub                             # web UI on http://127.0.0.1:8000
uv run backtest --symbol=2330             # one-shot vectorised backtest
uv run preload-prices --price-db exp.db --symbols 2330 --start 2026-10-01
uv run insight                            # diagnose the latest run
bash tests/test_cjtrade_integration_arenax.sh --broker=arenax --group=all  # shell smoke test (ArenaX)
CJ_CHECK_NO_SMOKE=1 uv run python scripts/check_readme_examples.py      # README examples
uv run --group docs mkdocs build --strict -d /tmp/site                  # docs site
```

Never run `bash tests/test_cjtrade_integration.sh --broker=sinopac` (the
`integration-cjshell-sinopac` pre-commit hook) on your own: it places **real** odd-lot
orders on the user's account. Commit with `SKIP=integration-cjshell-sinopac git commit ...`
unless the user asks for it. `/verify` (`.claude/commands/verify.md`) runs
the safe checks in CI order.

`testpaths` is `tests/unit` + `tests/integration`; `tests/manual/` is never
collected because its scripts read credentials at import time.

Lint (not in CI, but keep it clean):

```sh
uv run --with ruff ruff check --select F,E9 --no-cache --output-format concise <files>
```

Note `F403`/`F405` are everywhere already — `pkgs` uses star imports by
convention. Only new `F401`/`F811`/`F821` are your fault.

---

## 3. Layout

```
src/cjtrade/
  pkgs/
    brokers/        AccountClient (accounts + orders) + per-broker adapters
    marketdata/     MarketData sources (sinopac/finmind/yfinance/arenax/cache/offline) + Fallback, Cached
    models/         Order, Position, Product, Quote, Snapshot, Kbar, Trade, events
    strategy/       BaseStrategy + built-ins (bb, adx, dca, donchian, snr, baseline_0050)
    analytics/      technical (ta.*), fundamental, informational (news+LLM), backtest engine
    db/             sqlite / duckdb wrappers, order + fill ledgers
    ui/             FormEngine — TOML-declared forms, cli/zenity/web renderers
    config/         *.cjconf discovery and precedence
    paths.py        where user data lives (platformdirs)
    logger.py       get_logger / get_console / setup_logging
    llm/            unified LLM client (gemini / azure / ollama / mock)
    chart/          plotly kbar charts
  apps/
    ArenaX/         the simulated broker (server + 4 backends + market clock + price db)
    CJShell/        interactive shell (`cjshell`), CommandBase subclass per command
    CJTrade/        the trading app (`cjtrade`): engine, bots, status API
    FinHub/         web UI for the trading app (`finhub`, FastAPI, 127.0.0.1 only)
    CJEdit/ CJNews/ smaller apps
    oneshot_backtest.py, insight.py, preload_prices.py, strategy_tool.py
poc/                scratch space: poc/backtest.sh, experiments/ (research scripts)
tests/              unit / integration / manual, plus the shell test scripts
ref/                developer notes; ref/TOOLS.md lists every entry point
scripts/            config generators, README checker, price-db report
doc/                the docs site (mkdocs, en + zh-TW); images in doc/assets/img
.github/            CI, CodeQL, labeler + labels, release, Dependabot
.claude/            shared Claude Code settings and commands
```

Optional SDKs are extras (`sinopac`, `llm`, `news`, `finhub`, `all`) — see
`pkgs/utils/extras.py`. Import one inside `try`, and raise `missing_extra()`
where it is used, never at import time. `uv sync` installs them all through the
`dev` group.

---

## 4. Invariants — break these and things fail silently

**Datetime.** Every datetime in this codebase is a **naive Asia/Taipei**
value. Serialise with `.isoformat()` at every JSON boundary, parse with
`fromisoformat()`. **Never convert timezones anywhere.** Flask's default JSON
encoder turns `datetime` into an HTTP date (`"Mon, 01 Sep 2025 09:01:00 GMT"`)
whose `GMT` is a fiction — endpoints that pass a dataclass to `jsonify` leak
that format, so parse defensively (see `_parse_kbar` in
`pkgs/brokers/arenax/arenax_broker_api.py`).

**Prices come from a MarketData, not from a broker.** `pkgs/marketdata/base.py`
fixes the conventions: half-open `[start, end)` windows, intraday bars stamped
at their closing minute, daily bars at 09:00, raw prices, volume in lots. A
source that cannot serve a request raises `UnsupportedRequest` (never returns
`[]` for it), so `Fallback` moves on and `Cached` records nothing. ArenaX
backends take `market_data=`; `real_account` is only the account. New code
reads `client.market`; `AccountClient.get_kbars/get_snapshots/get_bid_ask`
are shims kept for existing callers.

Only **closed** bars are returned: a bar appears once its close (13:30 for a
daily bar) is at or before the source's `now()`, the wall clock for live
sources and the simulated clock for ArenaX's kbars route. Do not add a
"current bar" method; a forming bar is not data. Ticks are the finest level
(`aggregate.bars_from_ticks` makes 1m), and coarser bars come from 1m.
`CJTRADE_OFFLINE=1` makes network sources raise `MarketDataUnavailable`;
`arenaxd --data=offline --price-db=FILE` serves only a file filled by
`preload-prices`.

**No print(); log through `cjtrade.pkgs.logger`.** `log = get_logger("brokers.sinopac")`,
named for the path below `pkgs/` (or below `apps/`; the trading engine is
`engine.*`, bots `bot.<id>`). Lines read
`[INFO][2026-11-25 15:41:29] brokers.sinopac: message`. A tag such as `[Clock]`
is a logger name (`engine.clock`), never repeated in the message. Simulated
time goes in the message as `@2025-09-01 09:05`. A command's result (a shell
reply, a report, a table) is program output: `get_console(...)`, bare on
stdout. Only entry points call `setup_logging()`; `CJTRADE_LOG_LEVEL=DEBUG`
overrides the level.

**Engine code must be broker-agnostic.** Anything broker- or mode-specific
belongs in an init/bootstrap step, not in the loop. No clock stepping, no
`set_market_time`, no `if broker == "arenax"` inside engine logic. The one
allowed `if` is where the clock or broker is *constructed*.

**The engine feeds bars, not snapshots.** `src/cjtrade/apps/CJTrade/main.py`
publishes each symbol's closed 1m bars from `client.market.get_kbars` as a
`Kbar` (`protocol.PriceUpdate.bar`); a minute with no trade publishes nothing
and a `FeedStatus` says so. A replay's timeline comes from
`GET /api/v1/clock/timeline`, because the kbars route hides bars the server
clock has not reached.

**Market time vs system time.** `get_market_time()` is the canonical reader on
every broker (`mock_current_time`, `real_current_time`, `mock_init_time`,
`real_init_time`, `playback_speed`, `paused`). `get_system_time()` is a
deprecated alias. `set_timeline_origin()` sets where a replay *starts*;
`set_market_time()` moves the clock to a given moment.

**Account state snapshots are immutable.** `state_file` means "the snapshot to
**resume from**". Output always goes to a new `<uuid>.json` under
`paths.account_states_dir()` and never overwrites the input, so two runs from
the same snapshot are comparable. No `state_file` = fresh account. Identical
for all four backends.

**User data never lives in the repo.** Use `cjtrade.pkgs.paths`:

```python
from cjtrade.pkgs import paths
paths.price_db_path()        # ~/Library/Caches/cjtrade/arenax_price.db
paths.account_states_dir()   # ~/Library/Application Support/cjtrade/account_states/
paths.log_path("x.log")      # ~/Library/Logs/cjtrade/x.log
paths.describe()             # human-readable summary of all five categories
```

`CJTRADE_HOME` overrides all of them. Never hardcode `./data` or `~/...`.

**Config precedence.** First source to set a key wins (`override=False`):

```
env vars  >  ./.env  >  ./**/*.cjconf (depth, then alpha)  >  <user config dir>/*.cjconf  >  bundled *.cjsys
```

`config_sources()` / `describe_sources()` tell you where a key came from.
`*.cjconf` = secrets and user config. `*.cjsys` = app/server settings
(dotenv format, `AX_*` for the ArenaX server). FinHub's settings are
`FINHUB_*` env vars or `<config dir>/finhub.env`.

---

## 5. Testing

| dir | what | needs |
|---|---|---|
| `tests/unit/` | pure, no network, no disk | nothing |
| `tests/integration/arenax/` | real HTTP against ArenaX | `arenaxd` on :8801 (auto-skips if absent) |
| `tests/integration/cjtrade/` | `arenaxd` + `cjtrade` on 10 recorded days of 2357, fills compared exactly | ports 8802/5555/5556/8898 free (skips if not) |
| `tests/manual/` | scripts a human runs | credentials; not in `testpaths` |

Conventions in `tests/unit/`: mirror the source tree
(`tests/unit/pkgs/brokers/arenax/test_arenax_middleware.py`), one `class
TestX:` per unit under test, `@pytest.fixture` for setup, plain `assert`.
`tests/integration/conftest.py` is the reference for fixture style — it has a
`client` fixture with per-test `tmp_path`
isolation, a `make_order()` factory, and `likely_fill_*_price()` helpers.

Markers: `unit`, `integration`, applied by directory in `tests/conftest.py`
(no need to decorate). `pytest -m "not integration"` skips anything needing a
service.

Naming: name a test after the behaviour it checks, as a sentence
(`test_cancelling_a_filled_order_is_rejected`). No running numbers or
category codes (`test_E002_...`) — pytest runs tests in file order anyway.

Write tests when changing `pkgs/`. Don't add tests to `poc/` unless asked.

---

## 6. Naming conventions

- Packages/modules: `snake_case`. Broker adapters: `<broker>_broker_api.py`.
- ArenaX app classes carry an `ArenaX_` prefix: `ArenaX_BackendBase`,
  `ArenaX_Market`, `ArenaX_BrokerSideServer`, `ArenaX_AccountState`.
- Models are bare domain nouns: `Order`, `Position`, `Snapshot`, `Trade`.
- Enums are `str, Enum` so they compare equal to their wire string.
- Private helpers: single leading underscore. Module-level private constants
  too (`_SERVER_KEY_MAP`, `_RESTING`).
- Shell commands: `XxxCommand(CommandBase)`. The user-facing `name` is either
  a full word (`balance`, `help`, `kbars`) or a terse abbreviation
  (`lsodr`, `lspos`, `mvrs`) — match whichever family the neighbours use.
- Config keys: `AX_*` (ArenaX server), `FINHUB_*` (FinHub), `SINOPAC_*` and
  `FUBON_*` (broker credentials, read through `pkgs/config/broker_settings.py`;
  Sinopac's old unprefixed names still work with a warning), uppercase in
  `.cjconf`. `API_KEY` is ArenaX's key.
- Console scripts are lowercase (`cjtrade`, `cjshell`, `finhub`); app
  directories under `apps/` are the product name (`CJTrade`, `CJShell`,
  `FinHub`, `ArenaX`).
- Commits, branches and PRs: see §11.

---

## 7. Comment style — match this, not the recent commits

Many 2026-11 commits were largely AI-written and the
comments there are far too long. **Do not imitate them.** Write like the
2026-01..2026-06 code.

The house style:

- **Module docstring**: one-line summary, then a short `Usage::` block with a
  runnable example. Use `Parameters` / `Attributes` sections for public types.
- **Inline comments**: one line. Say what the thing *is* or what the
  non-obvious constraint *is*. Don't narrate the diff, don't explain what the
  code already says, don't write a paragraph of rationale.
- Taiwanese market terms in parentheses: `手續費`, `證交稅`, `六折`, `張`, `K線`,
  `標的`, `倉位`. Chinese is fine for a short intent note.
- Section separators when a file has distinct parts:
  `# ── Account queries ──────────────` or `# ------------------------------`
- `# TODO:` and `# NOTE:` are used and grepped (`scripts/gen_todos_report.sh`).
  Keep them one line.

Good (from `pkgs/models/cost.py`):

```python
commission_rate:     float = 0.001425    # 0.1425%
commission_discount: float = 1.0         # no discount
min_commission:      float = 20.0        # NT$20 minimum

stock_tax_rate: float = 0.003            # 0.3% SELL only
etf_tax_rate:   float = 0.001            # 0.1% SELL only for ETFs

def calc_tax(self, value: float, side: str, symbol: str) -> float:
    """Return transaction tax for a trade.  Zero for BUY; non-zero for SELL."""
```

Good (from `pkgs/brokers/arenax/arenax_broker_api.py`):

```python
# 所有 datetime 在 JSON 邊界都用 .isoformat() 序列化
# 接收方用 fromisoformat() 反序列化 任何地方不做 timezone 轉換!!
# 所有 datetime 都是 隱性台北時間的 naive datetime
```

Good (from `pkgs/analytics/backtest/engine.py`):

```python
# ---------------------------------------------------------------------------
# Simulated account (internal to engine)
# ---------------------------------------------------------------------------

class _SimAccount:
    """Minimal simulated brokerage account used by the engine."""
```

Bad — too long, explains history instead of the code:

```python
# Pass the broker's Snapshot through untouched. It used to be projected
# down to {symbol, close, timestamp}, which threw away the OHLC the bot
# then had to fake by setting open=high=low=close.
```

Shorten to:

```python
# Pass the broker's Snapshot through untouched (keeps real OHLC).
```

If a rationale genuinely needs three paragraphs, it belongs in `doc/` or a
commit message, not above the line.

---

## 8. API usage

### AccountClient — the one interface

Every broker is reached through `AccountClient`. Never instantiate a
`*BrokerAPI` directly; that is how broker-specific leaks get in.

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
from cjtrade.pkgs.models.product import Product

client = AccountClient(BrokerType.ARENAX, arenax_port=8802, api_key="testkey123")
client.connect()

client.get_balance()                       # float
client.get_positions()                     # List[Position]
client.get_account_state()                 # both, from one sync
client.get_snapshots([Product("2330")])    # List[Snapshot]
client.get_kbars(Product("2330"), "2025-09-01", "2025-09-08", "1m")
client.buy_stock("2330", quantity=3, price=1000.0, intraday_odd=True)
client.place_order(order)                  # keeps your Order.id
client.list_orders()                       # List[Trade] — includes resting orders
client.sync_state()                        # refresh committed orders
client.cancel_order(order_id)
client.get_market_time()                   # dict, same keys for every broker
client.control_plane                       # ArenaXMiddleWare, or None for a live broker
client.market                              # MarketData: get_kbars(symbol, start, end, interval)

client.disconnect()
```

`BrokerType` is `SINOPAC`, `FUBON`, `ARENAX`, and the unimplemented `YUANTA` / `CATHAY`.
`FUBON` (`pkgs/brokers/fubon/`, `fubon` extra) has no sandbox and serves quotes
but no bars; it has not been run against a live account.

### Kbar

`Kbar` carries its own `symbol`. Every strategy reads `bar.symbol`, and
`BacktestEngine` rejects a bar whose symbol is empty, so tag at the source:

```python
Kbar(ts, o, h, l, c, v, symbol="2317")
kbar.tagged("2317")             # copy with symbol set, for sources that know it one level up
Kbar.from_snapshot(snapshot)    # only for a caller that has nothing but a quote
```

`get_kbars()` on every broker already tags what it returns. Don't wrap `Kbar`
in a local bar class — that is what `_TaggedKbar` and `LiveBar` were, and both
are gone.

### Writing a strategy

```python
from cjtrade.pkgs.strategy import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    name = "MINE"

    def on_start(self, ctx):
        self._window = int(ctx.params.get("window", 20))

    def on_bar(self, bar, ctx):
        prices = ctx.prices(bar.symbol)
        if len(prices) < self._window:
            return []
        if bar.close < min(prices[-self._window:]) and not ctx.has_position(bar.symbol):
            qty = ctx.calc_qty(bar.close, 0.05)
            return [Signal("BUY", bar.symbol, qty, bar.close, "new low")]
        return []

    def on_fill(self, fill, ctx): ...
    def on_end(self, ctx): ...
```

All four hooks are **synchronous**. `on_bar` returns `List[Signal]`.
`StrategyContext` gives `timestamp, balance, equity, positions,
price_history, bar_index, params` plus `has_position()`, `position_qty()`,
`calc_qty()`, `prices()`.

`ctx.positions` is `List[Dict]` with the keys of `Position.to_dict()` —
not `Position` objects. See `pkgs/strategy/bb.py` for a complete real
strategy.

**`StrategyContext` has no notion of an open order.** A strategy cannot tell
that it already has a sell resting at the broker, which is why duplicate
signals happen. If you need that, it has to be handled by the runner.

### One-shot backtest

```python
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.strategy.bb import BollingerStrategy

engine = BacktestEngine(kbars=kbars, symbol="2330", initial_balance=1_000_000,
                        params={"bb__window_size": 20, "bb__min_width_pct": 0.01})
result = engine.run(BollingerStrategy())     # BacktestResult
```

In-memory, no HTTP, no clock. Use it as the baseline when checking whether
the trading engine (`cjtrade`) is correct; the two fill orders differently, so
compare trends, not exact numbers.

### Costs

```python
from cjtrade.pkgs.models.cost import CostModel

cm = CostModel(commission_discount=0.6, slippage_model="fixed_pct", slippage_pct=0.0005)
cm.calc_commission(value)             # 0.1425% × discount, min NT$20
cm.calc_tax(value, "SELL", "0050")    # 0.1% for ETFs, 0.3% otherwise, 0 for BUY
cm.buy_total(price, qty, symbol)      # (adj_price, notional, commission, tax)
```

### Technical indicators

```python
from cjtrade.pkgs.analytics.technical import ta

upper, middle, lower = ta.bb(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
ta.ema(closes, 12)
```

Backed by TA-Lib. `closes` is a `np.ndarray`. Slice to the window you need —
`bb.py` passes only the last `window` points so the allocation doesn't grow
with history.

### Forms (`pkgs/ui`)

Launch parameters are declared in TOML and collected by `FormEngine`, so one
schema serves a CLI prompt, a GTK dialog and a web form. Fields with a
`cli_arg` that appears in `sys.argv` are never prompted.

```python
from cjtrade.pkgs.ui.engine import FormEngine

answers = FormEngine("src/cjtrade/apps/CJTrade/form.toml", renderer="cli").run()
# {"broker": "arenax", "mode": "backtest", "watch_list": "2330", "fund": 500000, ...}
```

Field keys: `name`, `type`, `label`, `default`, `cli_arg`, `env_out`,
`persist_key`. `run_and_export()` / `print_exports()` feed a shell script via
`eval`.

### Shell commands

One `CommandBase` subclass per command in
`apps/CJShell/cjshell.py`. Set `name`, `description`, `params`,
`optional_params`, `example` in `__init__`, implement `execute(client, *args,
**kwargs)`, then add an instance to the list in `register_commands()`.
`validate_args()` is inherited and derives arity from `params` —
don't re-check it yourself. Keep `description` one line.

```python
class BalanceCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "balance"
        self.description = "Show account balance"
        self.example = "balance"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        out.info(f"Account Balance: {client.get_balance()}")   # out = get_console("CJShell")
```

---

## 9. Known traps

- `tests/manual/test_*.py` — 4 files fail collection (no credentials,
  `nacl ValueError`) if you point pytest at them. They are scripts; run them
  by hand.
- The pre-commit config runs the Sinopac shell test, which **places real
  orders**. Use `SKIP=integration-cjshell-sinopac` unless the user asked for it; never set
  `SINOPAC_SIMULATION=y` (or `SIMULATION=y`) in that hook to make it safe — the user keeps it real on
  purpose.
- ArenaX fills every order in full at its limit price: no partial fills,
  `PriceType.MKT` is matched as a limit, and the slippage setting is never
  applied.
- `AX_INITIAL_BALANCE` sets ArenaX's starting cash for a fresh account
  (no `AX_STATE_FILE`); FinHub sets it from the run's fund. The engine's
  `--fund` cannot change the server's balance, and only warns when they
  differ. Otherwise you get `DEFAULT_INITIAL_BALANCE = 100_000.0`.
- `seed_from_live` is never passed by any caller, so paper/real do **not**
  seed from the real account despite what the scripts' comments claim.
- Integration tests run against a random simulated start date. An order
  priced off a fixed number can fill or not depending on where the clock
  lands; price it from the market (`unlikely_fill_buy_price` and friends).
- `ArenaXBrokerAPI.register_order_callback` is a no-op placeholder. There is
  no fill callback; poll `list_orders()` or `sync_state()`.
- `sync_state()` only refreshes orders still in a `COMMITTED_*` status. An
  order that already filled is skipped, so **polling with `sync_state()`
  misses fills** — use `list_orders()`.
- `brokerside_server.py` passes dataclasses straight to `jsonify`, which
  works (Flask ≥2.2 handles dataclasses) but renders `datetime` as an HTTP
  date. Prefer `.to_dict()` in new endpoints.

---

## 10. Working agreements

- `.claude/settings.json` denies reading credentials and running anything
  that reaches a real Sinopac account; `/verify` runs the CI checks locally,
  `/offline-backtest` replays the engine on cached bars, and `/pr` follows §11.
- Answer the user in Traditional Chinese (繁體中文); code, comments, commit
  messages and PR text are in English.
- Don't reformat or "tidy" files you aren't changing. The star imports and
  the existing lint noise are deliberate background.
- Prefer fixing the root cause over the symptom, and say so in the commit.
- When adding a model-shaped concept, check `pkgs/models/` first. Don't ship a
  raw dict where a model exists.
- Leave the user's uncommitted experiment files (`exp/` in the main worktree,
  `poc/experiments/` outputs) alone: do not commit, move or delete them.
- Never push, force-push, tag, release or delete a branch until the user asks.

---

## 11. Branches, commits and PRs

**Branches.** `type/short-desc`, cut from the latest `origin/master`:
`feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`, `poc/` (e.g.
`feat/market-data`, `chore/release-automation`). The prefix sets the PR's
type label (`.github/labeler.yml`). One topic per branch.

**Commit messages.** Imperative subject, about 5–12 words, no trailing
period, no `type:` prefix: `Return only closed bars and let ArenaX run on an
offline price file`, `Rename the shell to CJShell and drop the test, atest
and main commands`. Body: at most **3 lines**, hard-wrapped at 72 columns,
saying what changed and why in plain sentences; no bullet lists, no
`Co-authored-by`. Check before committing:

```sh
printf '%s\n' "Subject line" "" "Body line one," "body line two." > /tmp/msg.txt
awk 'length > 72' /tmp/msg.txt          # must print nothing
SKIP=integration-cjshell-sinopac git commit -F /tmp/msg.txt
```

If the `reorder-python-imports` or `end-of-file-fixer` hook fails, it has
already fixed the files: `git add -A` and commit again with the same message.

**History.** Never change a commit's author or committer date, and keep the
order. Rewording an unpushed commit is fine; for a pushed one, ask first and
use `--force-with-lease`. A requested limit on the number of commits ("one
commit", "at most 8") is binding.

**PR titles.** `[type]: Sentence in plain English`, type matching the branch:
`[feat]: Make market data a separate dependency from the broker`,
`[chore]: Prepare the package and repository for a first release`,
`[doc]: Rewrite the README as a concise project overview`.

**PR descriptions.** Short; the diff has the details.

```markdown
One paragraph: what this PR does and why, for someone who has not read the code.

### Changes
- 3–6 bullets, one line each, the user-visible effect (not every file)

### Notes
- What a reviewer should know: behaviour changes, measured results, follow-ups

### Before merging
- Manual steps or ordering (merge #8 first, set a secret, ...); omit if none
```

Merge with **Create a merge commit** (no squash, no rebase); GitHub deletes
the branch. Labels are added automatically; `.github/labels.yml` defines
them and is synced to the repo on merge.

**Releases.** Bump `version` in `pyproject.toml` in a PR, then the user tags
`vX.Y.Z` on master. `release.yml` checks the tag against the version,
builds, waits for approval in the `pypi` environment, uploads with Trusted
Publishing and creates the GitHub Release. Never tag or publish yourself.
