"""Skip the ArenaX tests when no arenaxd is listening on :8801."""
import pytest
import requests


def _is_arenax_running() -> bool:
    try:
        requests.get("http://localhost:8801/health", timeout=1)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_arenax():
    """Skip every test here when the ArenaX server is not running."""
    if not _is_arenax_running():
        pytest.skip("ArenaX server not running — start it with `arenaxd` first")
