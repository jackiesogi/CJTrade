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
| `src/cjtrade/apps/` | Applications built on the SDK. ArenaX, cjtrade_shell, cjtrade_system, CJEdit, CJNews. |

Brokers: **Sinopac** (永豐金, real) and **ArenaX** (built-in simulated exchange).
Cathay / Yuanta are stubs.

**ArenaX is the important one.** It is a full broker-side server (Flask) with
its own clock, order book, matching loop and account state, so backtest /
paper / demo all speak the same HTTP API as a real broker. That is why
`AccountClient` code is identical across brokers.

ArenaX has four backends (`--backend=`):

| backend | market data | orders go to | real broker session |
|---|---|---|---|
| `backtest` | historical replay | ArenaX matching | yes (Sinopac, for data only) |
| `paper` | live feed | ArenaX matching | yes (data only) |
| `demo` | synthetic / cached | ArenaX matching | no |
| `real` | live feed | **real Sinopac** | yes — needs `I_UNDERSTAND_REAL_TRADING_RISKS=y` |

> `backtest` and `paper` **do log in to the real Sinopac account** to read
> prices, balance and positions. They never place real orders (only
> `real_backend.py` overrides `place_order`), but they burn API quota. For
> throwaway work use `demo`.

---

## 2. Commands

```sh
uv sync                                   # install
source .venv/bin/activate

uv run pytest tests/unit/ -q              # 148 tests, ~30s, no network
uv run pytest tests/integration/arenax/   # needs arenaxd on :8801
uv run arenaxd --backend=demo --port=8802 # ArenaX broker-side server
uv run cjtrade --broker=arenax            # interactive shell
uv run system --broker=arenax --mode=backtest   # full-simulation trading system
uv run backtest --symbol=2330             # one-shot vectorised backtest
uv run atest --broker=arenax --group=all  # shell smoke test (ArenaX)
```

**Do NOT run bare `uv run pytest`.** `tests/test_broker_api_stability.py:5` has
a module-level `raise SystemExit(0)`, which makes collection INTERNALERROR.
Always name a directory.

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
    brokers/        AccountClient (the one API users see) + per-broker adapters
    models/         Order, Position, Product, Quote, Snapshot, Kbar, Trade, events
    strategy/       BaseStrategy + built-ins (bb, adx, dca, donchian, snr, baseline_0050)
    analytics/      technical (ta.*), fundamental, informational (news+LLM), backtest engine
    db/             sqlite / duckdb wrappers, order + fill ledgers
    ui/             FormEngine — TOML-declared forms, cli/zenity/web renderers
    config/         *.cjconf discovery and precedence
    paths.py        where user data lives (platformdirs)
    llm/            unified LLM client (gemini / azure / ollama / mock)
    chart/          plotly kbar charts
    api/beginner.py Pine-Script-like facade for the strategy editor
    legacy/         don't touch
  apps/
    ArenaX/         the simulated broker (server + 4 backends + market clock + price db)
    cjtrade_shell/  interactive shell, CommandBase subclass per command
    cjtrade_system/ the automated system; system_launcher.py is the entry point
    CJEdit/ CJNews/ smaller apps
poc/                scratch space. trading_engine/ is the multi-bot ZMQ prototype
tests/              unit / integration / manual
ref/                design notes and captured logs, not code
scripts/            config and account-state generators
```

`currently_unused/` and `pkgs/legacy/` are dead. Don't read them for patterns,
don't update them.

---

## 4. Invariants — break these and things fail silently

**Datetime.** Every datetime in this codebase is a **naive Asia/Taipei**
value. Serialise with `.isoformat()` at every JSON boundary, parse with
`fromisoformat()`. **Never convert timezones anywhere.** Flask's default JSON
encoder turns `datetime` into an HTTP date (`"Mon, 01 Sep 2025 09:01:00 GMT"`)
whose `GMT` is a fiction — endpoints that pass a dataclass to `jsonify` leak
that format, so parse defensively (see `_parse_server_datetime` in
`poc/trading_engine/main2.py`).

**Engine code must be broker-agnostic.** Anything broker- or mode-specific
belongs in an init/bootstrap step, not in the loop. No clock stepping, no
`set_market_time`, no `if broker == "arenax"` inside engine logic. The one
allowed `if` is where the clock or broker is *constructed*.

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
(dotenv format, `AX_*` for the ArenaX server, `CJSYS_*` for the launcher).

---

## 5. Testing

| dir | what | needs |
|---|---|---|
| `tests/unit/` | pure, no network, no disk | nothing |
| `tests/integration/arenax/` | real HTTP against ArenaX | `arenaxd` on :8801 (auto-skips if absent) |
| `tests/manual/` | scripts a human runs | credentials; **4 of them fail collection** |
| `src/**/tests/` | package-local scratch tests | varies |

Conventions in `tests/unit/`: mirror the source tree
(`tests/unit/pkgs/brokers/arenax/test_arenax_middleware.py`), one `class
TestX:` per unit under test, `@pytest.fixture` for setup, plain `assert`.
`tests/integration/conftest.py` is the reference for fixture style — it has a
session-scoped auto-skip, a `client` fixture with per-test `tmp_path`
isolation, a `make_order()` factory, and `likely_fill_*_price()` helpers.

Markers: `unit`, `integration`. `pytest -m "not integration"` skips anything
needing a service.

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
- Config keys: `AX_*` (ArenaX server), `CJSYS_*` (launcher), uppercase in
  `.cjconf`.
- Commit messages: one short imperative line, ~5–9 words, no body unless it
  earns one. `Fix sync_state() semantics: place_order auto-commits`,
  `Add SignalCalculator as strategy base class`, `[Hotfix] Fix lsodr command`.

---

## 7. Comment style — match this, not the recent commits

Recent commits (2026-11, `Jackie Chen`) were largely AI-written and the
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
# _TaggedKbar – Kbar + symbol (Kbar model has no symbol field)
# ---------------------------------------------------------------------------

class _TaggedKbar:
    """Thin wrapper that attaches a symbol to a plain Kbar."""
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

client.disconnect()
```

`BrokerType.MOCK` is **broken** (`cjtrade.pkgs.brokers.arenax.legacy` does not
exist). It is still the default in `pkgs/api/beginner.py:create_client`.

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

In-memory, no HTTP, no clock. This is the reproducible path — use it as the
baseline when checking whether the full-simulation path is correct.

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

answers = FormEngine("poc/backtest_full_simulation.toml", renderer="cli").run()
# {"broker": "arenax", "mode": "backtest", "watch_list": "2330", "fund": 500000, ...}
```

Field keys: `name`, `type`, `label`, `default`, `cli_arg`, `env_out`,
`persist_key`. `run_and_export()` / `print_exports()` feed a shell script via
`eval`.

### Shell commands

One `CommandBase` subclass per command in
`apps/cjtrade_shell/cjtrade_shell.py`. Set `name`, `description`, `params`,
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
        balance = client.get_balance()
        print(f"Account Balance: {balance}")
```

---

## 9. Known traps

- `uv run pytest` (bare) → INTERNALERROR. Name a directory.
- `tests/manual/test_*.py` — 4 files fail collection (`KeyError: 'API_KEY'`,
  `nacl ValueError`). Expected; ignore them.
- `osystem` entry point in `pyproject.toml` points at a module that doesn't
  exist (`cjtrade_system.cjtrade_system`).
- `BrokerType.MOCK` → `ModuleNotFoundError`.
- The pre-commit config runs the Sinopac shell test, which **hits the real
  broker**. Know that before `git commit` without `--no-verify`.
- `base_backend.py:_check_price_in_time_range` indexes bars on a uniform
  minute grid from `start_date` and wraps with `idx = minute % n`. It drifts
  across days and wraps silently. `_calculate_kbar_index` in the same file
  does it correctly (binary search). This is the biggest open correctness
  issue in ArenaX.
- `_is_sufficient_account_inventory` / `_is_sufficient_account_balance`
  (`base_backend.py:843-851`) compare against **filled** position and cash
  only. Resting orders reserve nothing, so N identical sells all pass and the
  account can oversell. Same hole for cash on the buy side.
- There is **no** config key or endpoint that sets ArenaX's starting balance.
  `initial_balance` exists as a constructor kwarg but nothing passes it. The
  only working lever is `AX_STATE_FILE` / `CJSYS_STATE_FILE` pointing at a
  snapshot whose `"balance"` field holds the number — which is what
  `scripts/gen_init_account.sh` writes and `poc/backtest_full_simulation.sh`
  wires up. Otherwise you get `DEFAULT_INITIAL_BALANCE = 100_000.0`.
- `seed_from_live` is never passed by any caller, so paper/real do **not**
  seed from the real account despite what the scripts' comments claim.
- `db_api.py:386` has a mutable default evaluated at import
  (`updated_at: datetime = datetime.utcnow() + timedelta(hours=8)`).
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

- Keep `main.py` in `poc/trading_engine/` untouched — `main2.py` is the
  variant under development and the pair is kept for comparison.
- One commit per package when a change spans several.
- Don't reformat or "tidy" files you aren't changing. The star imports and
  the existing lint noise are deliberate background.
- Prefer fixing the root cause over the symptom, and say so in the commit.
- When adding a model-shaped concept, check `pkgs/models/` first. Don't ship a
  raw dict where a model exists.
