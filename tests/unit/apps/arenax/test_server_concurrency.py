"""The HTTP layer is concurrent; the backend behind it is not.

Checked against a real WSGI server on an ephemeral loopback port, because the
behaviour under test is werkzeug's threading and Flask's teardown ordering --
neither shows up through test_client().
"""
import threading
import time

import pytest
import requests
from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer
from cjtrade.apps.ArenaX.brokerside_server import DataReadiness


class _SlowBackend:
    """Counts how many threads are inside it at once."""

    def __init__(self, delay: float = 0.4):
        self.delay = delay
        self.concurrent = 0
        self.max_concurrent = 0
        self._guard = threading.Lock()
        self.account_state = type("S", (), {"initial_balance": 0.0, "balance": 0.0,
                                            "fill_history": []})()

    def _enter(self):
        with self._guard:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)

    def _leave(self):
        with self._guard:
            self.concurrent -= 1

    def _work(self, value):
        self._enter()
        try:
            time.sleep(self.delay)      # stands in for a yfinance preload
            return value
        finally:
            self._leave()

    # Only what the routes under test call.
    def is_connected(self):
        return True

    def account_balance(self):
        return self._work(1000.0)

    def list_positions(self):
        return []

    def list_trades(self):
        return []


@pytest.fixture
def server():
    srv = ArenaX_BrokerSideServer.__new__(ArenaX_BrokerSideServer)
    srv.backend = _SlowBackend()
    srv.host, srv.port = "127.0.0.1", 0          # 0 -> ephemeral
    srv._running = True
    srv._data_readiness = DataReadiness.ALL_SET
    srv._valid_api_keys = {"k"}
    srv._skip_non_trading_hours = False
    srv._backend_lock = threading.RLock()
    srv._http_server = None
    srv._app = srv._create_app()
    srv.start_http = lambda: None                # do not start the backend
    from werkzeug.serving import make_server
    httpd = make_server(srv.host, srv.port, srv._app, threaded=True)
    port = httpd.server_port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _get(base, path):
    return requests.get(base + path, timeout=10)


class TestBackendIsSerialised:
    def test_only_one_thread_enters_the_backend(self, server):
        srv, base = server
        results = []

        def hit():
            results.append(_get(base, "/api/v1/account").status_code)

        threads = [threading.Thread(target=hit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == [200, 200, 200, 200]
        # Without the lock this reaches 4 and the backend's lists race.
        assert srv.backend.max_concurrent == 1, srv.backend.max_concurrent


class TestHealthStaysAnswerable:
    def test_health_is_not_queued_behind_a_slow_backend_request(self, server):
        srv, base = server
        srv.backend.delay = 1.0

        slow = threading.Thread(target=lambda: _get(base, "/api/v1/account"))
        slow.start()
        time.sleep(0.15)                     # let it get inside the backend

        t0 = time.perf_counter()
        r = _get(base, "/health")
        elapsed = time.perf_counter() - t0
        slow.join()

        assert r.status_code == 200
        # Single-threaded werkzeug used to make this wait out the slow handler.
        assert elapsed < 0.5, f"/health waited {elapsed:.2f}s behind the backend"

    def test_docs_are_not_queued_either(self, server):
        srv, base = server
        srv.backend.delay = 1.0
        slow = threading.Thread(target=lambda: _get(base, "/api/v1/account"))
        slow.start()
        time.sleep(0.15)
        t0 = time.perf_counter()
        codes = (_get(base, "/docs").status_code,
                 _get(base, "/openapi.json").status_code)
        elapsed = time.perf_counter() - t0
        slow.join()
        assert codes == (200, 200)
        assert elapsed < 0.5, f"docs waited {elapsed:.2f}s"


class TestLockIsNotLeaked:
    def test_a_handler_that_raises_still_releases(self, server):
        srv, base = server

        def boom():
            raise RuntimeError("handler blew up")

        srv.backend.account_balance = boom
        assert _get(base, "/api/v1/account").status_code == 500
        # If teardown had not released, this would hang until the timeout.
        srv.backend.account_balance = lambda: 1.0
        assert _get(base, "/api/v1/account").status_code == 200
        assert srv._backend_lock.acquire(blocking=False) is True
        srv._backend_lock.release()


if __name__ == "__main__":
    pytest.main([__file__])
