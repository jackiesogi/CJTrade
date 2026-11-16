# Root conftest.py — applies to all tests under tests/
#
# Layout:
#   tests/unit/        Pure unit tests (no network, no disk I/O)
#   tests/integration/ Tests that require an ArenaX server or real broker
#   tests/manual/      Scripts run by hand against a real broker. Not collected.
#
# Run commands:
#   pytest                      # unit + integration (integration skips itself
#                               # when no ArenaX server is listening)
#   pytest tests/unit/          # only unit tests
#   pytest tests/integration/   # only integration tests
#   pytest -m "not integration" # skip anything needing external services
#
# Naming: a test is named after the behaviour it checks, as a sentence
# (test_cancelling_a_filled_order_is_rejected), never after a running number.
# pytest already runs tests in the order they are written, so a number adds
# nothing but a sequence to keep renumbering.
from pathlib import Path

import pytest

_TESTS = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Mark every test by the directory it lives in.

    Keeps the `unit` / `integration` markers registered in pyproject.toml true
    without asking each file to remember to declare them.
    """
    for item in items:
        try:
            top = Path(item.fspath).relative_to(_TESTS).parts[0]
        except ValueError:
            continue
        if top in ("unit", "integration"):
            item.add_marker(getattr(pytest.mark, top))
