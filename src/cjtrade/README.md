# Source code in `apps`

See [here](./apps/README.md)

# Source code in `pkgs`

`pkgs` is the SDK. Nothing in here knows about an app, so anything an app does
twice belongs below.

## `analytics/`

Commonly-used analytics methods, grouped by the kind of question they answer.

- **Fundamental (基本面)**: EPS, PB ratio, PE ratio, dividends, company info and
  TWSE announcements.
- **Technical (技術面)**: SMA, MACD, RSI and the rest, as a thin wrapper over
  TA-Lib.
- **Informational (消息面)**: news scraped from Cnyes (鉅亨網), StatementDog and
  NewsAPI, with an LLM doing the sentiment analysis.
- **Backtest and evaluation**: the bar-by-bar backtest engine, and the
  quantstats tearsheets and multi-strategy comparison reports built from its
  results.

## `api/`

A deliberately small, friendly surface (`beginner.py`) for someone at a REPL
who wants to buy something without first learning what an `AccountClient` is.
It holds a broker session and places orders itself, which is why strategies use
`strategy/authoring.py` instead.

## `brokers/`

**Integration with each broker's API** — Sinopac (永豐金證券), Cathay
(國泰證券), ArenaX (the built-in simulator) — behind one interface, so an app
written once can be pointed at a different broker without being rewritten.

See [here](./pkgs/brokers/README.md) for more info.

## `chart/`

Drawing, rendering and saving K-bar (K線) charts.

## `config/`

Reads the `*.cjconf` files that `scripts/gen_config.sh` generates — broker
credentials, LLM keys and other per-user settings — from the current directory
first and the user config directory after. One rule governs the whole search:
the first source to set a key wins, so an environment variable you exported
cannot be displaced by a file.

## `db/`

Database core operations. SQLite (and a DuckDB backend alongside it) behind one
small API, plus the schemas under `sql/` for the price cache and the local
order and fill ledgers, so callers do not write SQL by hand.

## `legacy/`

Don't touch it.

## `llm/`

A unified interface to different LLM services, with a pool in front so a
failing backend falls through to the next one. Available backends: Gemini,
Azure OpenAI, and a mock for tests.

## `models/`

Common data types for the whole project, for example

- `Position` (倉位)
- `Order` (訂單) and `OrderResult`
- `Product` (金融商品)
- `Quote` / `Snapshot` (報價)
- `Kbar` (K線)
- `Trade` (成交)

and more. If two packages need to agree on the shape of something, the shape
lives here.

## `risk/`

Pre-trade checks (`pre_trade.py`): the questions that must be answered before
an order is allowed out, separate from whichever strategy asked for it.

## `strategy/`

The strategies themselves (Bollinger Bands, Donchian breakout, support and
resistance, ADX regime switching, DCA, and a buy-and-hold baseline), the
`BaseStrategy` contract they implement, and the per-interval parameter presets.

`authoring.py` is the module a hand-written strategy imports. It is the whole
vocabulary such a file may use and it reaches no broker session: `buy()` there
returns an *intent*, and something above the strategy decides whether to place
it.

## `ui/`

Renders a form from a TOML description, to the CLI, a browser or Zenity, and
remembers the answers between runs. This is what lets `poc/backtest.sh` be both
interactive and scriptable — a field whose flag is on the command line is never
prompted for.

## `utils/`

Small shared helpers: date arithmetic, and a cross-platform `ncal` for printing
a month in the terminal.

## `paths.py`

Where this machine keeps its data: price cache, reports, state, logs and
config. Call it instead of hardcoding a path, and honour `CJTRADE_HOME` for
free.
