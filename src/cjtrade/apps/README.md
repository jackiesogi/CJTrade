# CJTrade apps

These are the built-in apps. They are all written against the CJTrade SDK and
hold no privileged access of their own, so each one doubles as a worked example
of what the SDK can do.

| App | What it is | Launch | Reference |
|-----|------------|--------|-----------|
| CJTrade Shell | Interactive shell for trading and poking at the API | `uv run cjshell --broker=arenax` | [README](./CJShell/README.md) |
| CJTrade | The trading app: an engine running each strategy as a bot | `uv run cjtrade --broker=arenax --mode=backtest` | [README](./CJTrade/README.md) |
| ArenaX | Simulated broker: market data, matching, portfolio | `uv run arenaxd` | [README](./ArenaX/README.md) |
| CJNews | Financial news search engine | `uv run python src/cjtrade/apps/CJNews/main.py` | [README](./CJNews/README.md) |
| CJEdit | Browser-based editor for quick strategy tests | `uv run python src/cjtrade/apps/CJEdit/main.py` | [README](./CJEdit/README.md) |
| insight | Turns a finished backtest into a report you can diagnose | `uv run insight` | — |
| strategy-tool | The strategy-authoring API as a CLI, for callers outside this process | `uv run strategy-tool templates` | — |
