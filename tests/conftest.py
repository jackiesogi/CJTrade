# Root conftest.py — applies to all tests under tests/
#
# Layout:
#   tests/unit/        Pure unit tests (no network, no disk I/O)
#   tests/integration/ Tests that require an ArenaX server or real broker
#
# Run commands:
#   pytest                      # all tests
#   pytest tests/unit/          # only unit tests
#   pytest tests/integration/   # only integration tests
#   pytest -m "not integration" # skip anything needing external services
