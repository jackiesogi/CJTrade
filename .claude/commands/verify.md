---
description: Run the checks CI runs, without the Sinopac test, and report what failed
---
Run these from the repo root, in order, and stop at the first failure to
investigate it:

1. `uv run pytest tests/unit -q -p no:cacheprovider`
2. `CJ_CHECK_NO_SMOKE=1 uv run python scripts/check_readme_examples.py`
3. `uv run --group docs mkdocs build --strict -d /tmp/cjtrade-site`
4. `uv lock --check`

Do not run `bash tests/test_cjtrade_integration.sh --broker=sinopac` or the
`integration-cjshell-sinopac` pre-commit
hook: it logs in to a real Sinopac account and places real odd-lot orders.
The ArenaX integration tests (`tests/integration/arenax`) start a local
server on 8801; run them only if nothing else is using that port.

Report each step as passed or failed, with the failing test names and the
first error, and nothing else.
