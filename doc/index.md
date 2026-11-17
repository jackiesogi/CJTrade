# CJTrade

CJTrade is a Python framework for building trading systems for the Taiwan
Stock Exchange (TWSE). You write a strategy against the CJTrade API, and the
same strategy runs against any supported broker:

- **ArenaX**, the built-in simulated broker, for demos, paper trading and
  backtesting. It runs as a local HTTP server (`uv run arenaxd`).
- **Sinopac** (永豐金證券), a real broker, through its `shioaji` SDK.

!!! danger "Not investment advice"
    CJTrade can place real orders on a real brokerage account. You are
    responsible for every order it sends. Try a strategy against ArenaX
    first, then against Sinopac with `SIMULATION=y`, before you let it touch
    real money.

## Install

From a checkout, which also gives you the apps and the test suites:

```sh
git clone https://github.com/jackiesogi/CJTrade
cd CJTrade
uv sync
```

As a package. The core covers ArenaX, backtesting, the shell and reports;
each integration is an extra:

```sh
pip install 'cjtrade[sinopac,llm] @ git+https://github.com/jackiesogi/CJTrade'
```

| Extra | Adds | Needed for |
|---|---|---|
| `sinopac` | `shioaji` | the Sinopac broker, and ArenaX's `backtest` / `paper` backends |
| `llm` | `google-genai`, `openai` | LLM clients (Gemini, Azure OpenAI) |
| `news` | `newsapi-python` | the NewsAPI news source |
| `all` | all of the above | |

## Where to go next

| You want to | Read |
|---|---|
| Start the simulated broker and connect to it | [Connect to a broker](get-started/connect.md) |
| Read the account, place and cancel an order | [Account and orders](get-started/account-and-orders.md) |
| Get quotes, historical bars and indicators | [Market data](get-started/market-data.md) |
| Write a strategy file and check it | [Write a strategy](get-started/strategy.md) |
| Run a strategy over historical bars | [Backtesting](get-started/backtesting.md) |
| Look up a class or function | [API reference](reference/account-client.md) |

The apps (interactive shell, ArenaX server, the trading engine, `insight`)
are documented in the
[README on GitHub](https://github.com/jackiesogi/CJTrade#readme).

!!! note
    The API is not stable yet; names may change before 1.0.
