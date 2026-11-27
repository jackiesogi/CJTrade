# API reference

These pages are generated from the code's docstrings. Each lists a module's
classes and functions with their parameters; use the search box, or the
table below, to find the right page.

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

Reading a page:

- A heading with a small `class` or `func` label is one class or function.
  Its first paragraph says what it is; **Parameters** lists the arguments,
  **Returns** what comes back, **Raises** the errors.
- Click **Source code** under an entry to see its implementation.
- Names starting with `_` are internal and not listed.

If you are new to CJTrade, the [Get started](../get-started/install.md) pages
explain the same objects with examples.
