# Integration tests

Real HTTP against an ArenaX server. Every test here skips itself when nothing
is listening on `127.0.0.1:8801`, so a plain `uv run pytest` is safe without
one.

```sh
# Starts arenaxd if needed, runs tests/integration/arenax, writes coverage
bash tests/run_broker_stability_tests.sh --broker=arenax --coverage
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
