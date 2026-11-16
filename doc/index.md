# CJTrade

CJTrade is a Python framework for building trading systems for the Taiwan
Stock Exchange (TWSE). You write a strategy against the CJTrade API, and the
same strategy runs against any supported broker without being rewritten:
ArenaX, the built-in simulated broker, for paper trading and backtesting, and
Sinopac (永豐金證券) for real trading.

!!! warning "Not investment advice"
    CJTrade can place real orders on a real brokerage account. You are
    responsible for every order it sends. Run a strategy in ArenaX, then with
    Sinopac's `SIMULATION=y`, before you let it touch real money.

## Install

From a checkout, which also gives you the apps and the test suites:

```sh
git clone https://github.com/jackiesogi/CJTrade
cd CJTrade
uv sync
```

As a package. The core covers ArenaX, backtesting, the shell and reports; each
integration is an extra:

```sh
pip install 'cjtrade[sinopac,llm] @ git+https://github.com/jackiesogi/CJTrade'
```

| Extra | Adds | Needed for |
|---|---|---|
| `sinopac` | `shioaji` | the Sinopac broker, and ArenaX's `backtest` / `paper` backends |
| `llm` | `google-genai`, `openai` | LLM advice (Gemini, Azure OpenAI) |
| `news` | `newsapi-python` | the NewsAPI news source |
| `all` | all of the above | |

## Where to go next

- **Write a strategy for the trading engine**:
  [Strategy authoring](reference/strategy-authoring.md) is the whole
  vocabulary a strategy file may use.
- **Write a class-based strategy for the oneshot backtester**:
  [BaseStrategy](reference/base-strategy.md).
- **Talk to a broker directly**: [AccountClient](reference/account-client.md).
- **Run the apps** (shell, ArenaX server, backtests, `insight`): see the
  [README on GitHub](https://github.com/jackiesogi/CJTrade#readme).

The API is not stable yet; expect names to change before 1.0.
