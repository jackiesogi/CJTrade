# Integration tests

- `arenax/`: real HTTP against an ArenaX server. Skips itself when nothing
  is listening on `127.0.0.1:8801`.
- `cjtrade/`: the trading engine end to end. Starts its own `arenaxd` on
  8802 with `--data=offline`, loads `cjtrade/fixtures/2357_1m.csv.gz` (Sinopac
  1m bars, 2024-04-29 .. 2024-05-24), replays 10 days and compares every
  fill with a recorded run. No network; about 45 seconds. If a change is
  meant to alter how the engine trades, re-record the expected fills in
  `test_engine_backtest.py` and say why in the commit.

```sh
# Starts arenaxd if needed, runs tests/integration/arenax, writes coverage
bash tests/run_broker_stability_tests.sh --broker=arenax --coverage
uv run pytest tests/integration/cjtrade
```

Name a test after the behaviour it checks, as a sentence
(`test_cancelling_a_filled_order_is_rejected`), not after a running number.

Integration test priority:
- `broker`
- `db`
- `llm`
- `model`
- `config`
- `analytics`
- `strategy`
- `utils`

Aimed to reach 100% code coverage.
