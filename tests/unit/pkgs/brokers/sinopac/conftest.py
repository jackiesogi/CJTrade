# These tests import the Sinopac adapter, which needs shioaji from the
# 'sinopac' extra. Without it, skip the directory instead of failing
# collection: `uv sync` alone installs only the core.
import importlib.util

collect_ignore_glob = [] if importlib.util.find_spec("shioaji") else ["test_*.py"]
