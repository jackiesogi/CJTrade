# CJTrade apps

These are the built-in apps. They are all written against the CJTrade SDK and
hold no privileged access of their own, so each one doubles as a worked example
of what the SDK can do.

| App | What it is | Launch | Reference |
|-----|------------|--------|-----------|
| CJTrade Shell | Interactive shell for trading and poking at the API | `uv run cjtrade --broker=arenax` | [README](./cjtrade_shell/README.md) |
| CJTrade System | Automated trading system (paper / real / replay) | `uv run system --broker=arenax --mode=demo` | [README](./cjtrade_system/README.md) |
| ArenaX | Simulated broker: market data, matching, portfolio | `uv run arenaxd` | [README](./ArenaX/README.md) |
| CJNews | Financial news search engine | `uv run python src/cjtrade/apps/CJNews/main.py` | [README](./CJNews/README.md) |
| CJEdit | Browser-based editor for quick strategy tests | `uv run python src/cjtrade/apps/CJEdit/main.py` | [README](./CJEdit/README.md) |
| insight | Turns a finished backtest into a report you can diagnose | `uv run insight` | — |
| strategy-tool | The strategy-authoring API as a CLI, for callers outside this process | `uv run strategy-tool templates` | — |

The trading engine is not in here. It lives in `poc/trading_engine/` because it
spawns one OS process per strategy and talks to them over ZeroMQ, which makes
it a system rather than an app. See the project root README.
