# API reference

The API pages are generated from docstrings. Each covers one module's
classes and functions with their parameters. Find a page with search or the
table below.

| You want to | Page |
|---|---|
| Connect, read the account, place orders | [AccountClient](account-client.md) |
| Write your own broker adapter | [Broker interface](broker-base.md) |
| Talk to ArenaX directly, including its clock | [ArenaX client](arenax-client.md) |
| Know what the Sinopac adapter does | [Sinopac adapter](sinopac.md) |
| Write a strategy file | [Strategy authoring](strategy-authoring.md), [Loading strategy files](user-strategy.md) |
| Write a class-based strategy | [BaseStrategy](base-strategy.md), [Built-in strategies](strategies.md), [Strategy parameters](strategy-parameters.md) |
| Get prices from any source | [Market data](market-data.md) |
| Know the fields of an order, bar or position | [Models](models.md) |
| Backtest in memory | [Backtest engine](backtest-engine.md), [Cost model](cost-model.md) |
| Check orders before they are sent | [Risk gate](risk.md) |
| Indicators, reports, news, fundamentals, LLMs, charts | [Analytics](technical.md) section |
| Settings and where files go | [Configuration and paths](config.md) |
| Build a form for a script | [Forms](forms.md) |

Page conventions:

- Each heading labelled `class` or `func` is one class or function. Its
  first paragraph describes it; **Parameters** lists the arguments,
  **Returns** the return value, **Raises** the exceptions.
- **Source code** under an entry expands its implementation.
- Names starting with `_` are internal and omitted.

The [Get started](../get-started/install.md) pages cover the same objects
with worked examples.
