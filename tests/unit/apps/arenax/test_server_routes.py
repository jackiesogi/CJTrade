"""HTTP routes of the ArenaX broker-side server, driven through Flask's test_client."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.apps.ArenaX import brokerside_server as bss
from cjtrade.apps.ArenaX.backtest_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer
from cjtrade.apps.ArenaX.brokerside_server import DataReadiness
from cjtrade.pkgs.marketdata import Capabilities
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar

MON = datetime(2025, 9, 1)          # Monday


def at(h, m=0, day=0):
    return MON.replace(hour=h, minute=m) + timedelta(days=day)


class _Source(MarketData):
    """Five sessions of 1m bars at 100, dipping to 95 at 10:00-10:29."""
    name = "fake"

    def __init__(self, fail=False):
        self.fail = fail

    @property
    def capabilities(self):
        return Capabilities(intervals=frozenset({"1m"}))

    def get_kbars(self, symbol, start, end, interval="1m"):
        if self.fail:
            raise RuntimeError("source down")
        self.require_interval(interval)
        start, end = to_window(start, end)
        bars = []
        for d in range(5):
            for m in range(1, 271):
                ts = at(9, day=d) + timedelta(minutes=m)
                c = 95.0 if 600 <= ts.hour * 60 + ts.minute < 630 else 100.0
                bars.append(Kbar(ts, c, c, c, c, 1000, symbol))
        return in_window(bars, start, end)


class _Broker:
    """A connected real account, as far as the routes look."""
    def __init__(self, name="sinopac", positions=(), fail=False):
        self.name, self.positions, self.fail = name, list(positions), fail

    def is_connected(self):
        return True

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_broker_name(self):
        if self.fail:
            raise RuntimeError("session dropped")
        return self.name

    def get_positions(self):
        return self.positions


def _server(backend, running=True):
    srv = ArenaX_BrokerSideServer(backend=backend, port=0)
    srv._running = running
    srv._data_readiness = DataReadiness.ALL_SET
    srv._skip_non_trading_hours = False
    srv._backend_str = "backtest"           # no keepalive thread
    srv._match_interval = 0.01
    return srv


@pytest.fixture
def backend(tmp_path):
    b = ArenaX_Backend_Historical(
        market_data=_Source(), backtest_start_date=MON, initial_balance=100_000.0,
        price_db_path=str(tmp_path / "price.db"), state_dir=str(tmp_path / "states"),
        num_days_preload=3)
    assert b.login()
    b.market.set_market_time(at(9, 30))
    return b


@pytest.fixture
def srv(backend):
    return _server(backend)


@pytest.fixture
def client(srv):
    return srv._app.test_client()


def _order_body(**over):
    body = {
        "product": {"symbol": "2330"}, "action": "BUY", "price": 96.0, "quantity": 10,
        "price_type": "LMT", "order_type": "ROD", "order_lot": "Common",
        "created_at": at(9, 30).isoformat(), "opt_field": {"session_id": "s1"},
        "id": "client-id-1",
    }
    body.update(over)
    return body


def _fill_one(client, srv, **over):
    """POST a BUY at 09:30 and step the clock over the 10:00 dip."""
    assert client.post("/api/v1/orders", json=_order_body(**over)).status_code == 200
    srv.backend.market.set_market_time(at(10, 15))
    client.get(f"/api/v1/orders/{over.get('id', 'client-id-1')}")


class TestReadinessGate:
    def test_trading_routes_answer_503_until_the_backend_runs(self, backend):
        client = _server(backend, running=False)._app.test_client()
        r = client.get("/api/v1/account")
        assert r.status_code == 503
        assert r.get_json()["ok"] is False

    def test_health_is_served_while_the_backend_is_down(self, backend):
        client = _server(backend, running=False)._app.test_client()
        body = client.get("/health").get_json()
        assert body == {"ok": True, "running": False, "backend": "backtest",
                        "backend_connected": True, "data_readiness": "all_set"}

    def test_the_backend_route_is_reachable_while_down(self, backend):
        client = _server(backend, running=False)._app.test_client()
        assert client.put("/api/v1/backend", json={}).status_code == 400


class TestBackendRoute:
    def test_running_is_required(self, client):
        r = client.put("/api/v1/backend", json={})
        assert r.status_code == 400
        assert "running" in r.get_json()["error"]

    def test_stopping_and_starting_the_backend(self, backend):
        srv = _server(backend, running=False)
        client = srv._app.test_client()
        assert client.put("/api/v1/backend", json={"running": True}).get_json() == \
            {"ok": True, "running": True}
        assert srv._matching_thread.is_alive()
        assert client.put("/api/v1/backend", json={"running": False}).get_json() == \
            {"ok": True, "running": False}
        assert not srv._matching_thread.is_alive()
        assert not backend.is_connected()

    def test_a_failed_login_is_reported_and_the_server_stays_down(self, backend):
        srv = _server(backend, running=False)
        backend.login = lambda: False
        r = srv._app.test_client().put("/api/v1/backend", json={"running": True})
        assert r.status_code == 500
        assert r.get_json()["running"] is False
        assert "login failed" in r.get_json()["error"]
        assert srv._running is False


class TestSession:
    def test_a_valid_api_key_logs_in(self, client):
        r = client.post("/api/v1/session", json={"api_key": "testkey123"})
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_an_invalid_api_key_is_refused(self, client):
        r = client.post("/api/v1/session", json={"api_key": "wrong"})
        assert r.status_code == 401
        assert r.get_json()["ok"] is False

    def test_logging_out_always_succeeds(self, client):
        assert client.delete("/api/v1/session").get_json()["ok"] is True


class TestConfigRoute:
    def test_secrets_in_the_config_are_withheld(self, client, monkeypatch):
        monkeypatch.setitem(bss.external_config, "api_key", "live-key")
        body = client.get("/api/v1/config").get_json()
        assert body["external_config"]["api_key"] == "<redacted>"
        assert "live-key" not in str(body)


class TestOrderRoutes:
    def test_placing_an_order_keeps_the_callers_id(self, client, srv):
        r = client.post("/api/v1/orders", json=_order_body())
        body = r.get_json()
        assert r.status_code == 200
        assert body["result"]["status"] == "COMMITTED_WAIT_MATCHING"
        assert body["result"]["linked_order"] == "client-id-1"
        assert [o.id for o in srv.backend.account_state.orders_committed] == ["client-id-1"]

    @pytest.mark.parametrize("missing", ["product", "action", "price", "quantity",
                                         "price_type", "order_type", "order_lot"])
    def test_a_missing_required_field_is_a_400(self, client, missing):
        body = _order_body()
        del body[missing]
        assert client.post("/api/v1/orders", json=body).status_code == 400

    def test_a_zero_price_reaches_the_backend_and_is_rejected(self, client):
        body = client.post("/api/v1/orders", json=_order_body(price=0)).get_json()
        assert body["ok"] is True
        assert body["result"]["status"] == "REJECTED"

    def test_an_unknown_enum_value_is_a_500_with_the_reason(self, client):
        r = client.post("/api/v1/orders", json=_order_body(action="HOLD"))
        assert r.status_code == 500
        assert "HOLD" in r.get_json()["error"]

    @pytest.mark.parametrize("lot, expected", [("IntraDayOdd", "IntraDayOdd"),
                                               ("true", "IntraDayOdd"),
                                               ("odd-ish", "Common")])
    def test_an_order_lot_outside_the_enum_falls_back_to_a_boolean_reading(
            self, client, srv, lot, expected):
        client.post("/api/v1/orders", json=_order_body(order_lot=lot))
        assert srv.backend.account_state.orders_committed[0].order_lot.value == expected

    def test_a_plain_string_product_is_read_as_a_symbol(self, client, srv):
        client.post("/api/v1/orders", json=_order_body(product="2317"))
        assert srv.backend.account_state.orders_committed[0].product.symbol == "2317"

    def test_get_order_refreshes_and_reports_the_fill(self, client, srv):
        client.post("/api/v1/orders", json=_order_body())
        srv.backend.market.set_market_time(at(10, 15))
        r = client.get("/api/v1/orders/client-id-1")
        assert r.get_json()["result"]["status"] == "FILLED"

    def test_get_order_for_an_unknown_id_is_rejected(self, client):
        assert client.get("/api/v1/orders/nope").get_json()["result"]["status"] == "REJECTED"

    def test_cancelling_a_resting_order(self, client, srv):
        client.post("/api/v1/orders", json=_order_body())
        body = client.delete("/api/v1/orders/client-id-1").get_json()
        assert body["result"]["status"] == "CANCELLED"
        assert srv.backend.account_state.orders_committed == []

    def test_cancelling_a_filled_order_is_rejected(self, client, srv):
        _fill_one(client, srv)
        body = client.delete("/api/v1/orders/client-id-1").get_json()
        assert body["result"]["status"] == "REJECTED"

    def test_a_backend_error_in_cancel_or_get_is_a_500(self, client, srv):
        def boom(_):
            raise RuntimeError("broken")
        srv.backend.cancel_order = boom
        srv.backend.sync_state = boom
        assert client.delete("/api/v1/orders/x").status_code == 500
        assert client.get("/api/v1/orders/x").get_json()["error"] == "broken"

    def test_open_only_lists_just_the_resting_orders(self, client, srv):
        _fill_one(client, srv)
        client.post("/api/v1/orders", json=_order_body(id="resting", price=50.0,
                                                       created_at=at(10, 15).isoformat()))
        every = client.get("/api/v1/orders").get_json()["orders"]
        open_ = client.get("/api/v1/orders?open_only=true").get_json()["orders"]
        assert {o["id"] for o in every} == {"client-id-1", "resting"}
        assert [o["id"] for o in open_] == ["resting"]


class TestAccountRoutes:
    def test_account_reports_balance_positions_and_orders_together(self, client, srv):
        _fill_one(client, srv)
        body = client.get("/api/v1/account").get_json()
        assert body["balance"] == pytest.approx(100_000.0 - 980.0)
        assert [(p["symbol"], p["quantity"]) for p in body["positions"]] == [("2330", 10)]
        assert [o["status"] for o in body["orders"]] == ["FILLED"]

    def _seed_fills(self, srv, n=5):
        srv.backend.account_state.fill_history = [
            {"order_id": f"o{i}", "session_id": "a" if i % 2 else "b"} for i in range(n)]

    def test_fills_report_the_balance_bracket(self, client, srv):
        _fill_one(client, srv)
        body = client.get("/api/v1/account/fills").get_json()
        assert body["initial_balance"] == 100_000.0
        assert body["final_balance"] == pytest.approx(99_020.0)
        assert body["fill_history"][0]["session_id"] == "s1"
        assert (body["total"], body["truncated"]) == (1, False)

    def test_fills_can_be_filtered_by_session(self, client, srv):
        self._seed_fills(srv)
        body = client.get("/api/v1/account/fills?session_id=a").get_json()
        assert [f["order_id"] for f in body["fill_history"]] == ["o1", "o3"]
        assert body["total"] == 2

    def test_a_limit_keeps_the_most_recent_and_says_it_truncated(self, client, srv):
        self._seed_fills(srv)
        body = client.get("/api/v1/account/fills?limit=2").get_json()
        assert [f["order_id"] for f in body["fill_history"]] == ["o3", "o4"]
        assert (body["total"], body["truncated"]) == (5, True)

    def test_a_non_positive_limit_returns_everything(self, client, srv):
        self._seed_fills(srv)
        assert len(client.get("/api/v1/account/fills?limit=0").get_json()["fill_history"]) == 5

    def test_a_non_numeric_limit_is_a_400(self, client):
        assert client.get("/api/v1/account/fills?limit=ten").status_code == 400


class TestClockRoutes:
    def test_reading_the_clock(self, client):
        body = client.get("/api/v1/clock").get_json()
        assert body["mock_current_time"] == at(9, 30).isoformat()
        assert body["mock_init_time"] == at(9).isoformat()
        assert body["paused"] is True
        assert body["paused_time"] == at(9, 30).isoformat()

    def test_patching_the_time_moves_and_freezes_the_clock(self, client, srv):
        r = client.patch("/api/v1/clock", json={"mock_current_time": at(11).isoformat()})
        assert r.get_json() == {"ok": True, "mock_current_time": at(11).isoformat()}
        assert srv.backend.market.get_market_time()["mock_current_time"] == at(11)

    def test_resuming_and_pausing_the_clock(self, client, srv):
        r = client.patch("/api/v1/clock", json={"paused": False}).get_json()
        assert (r["paused"], r["mock_current_time"]) == (False, at(9, 30).isoformat())
        assert srv.backend.market.paused is False
        assert client.patch("/api/v1/clock", json={"paused": True}).get_json()["paused"] is True
        assert srv.backend.market.paused is True

    def test_an_empty_patch_is_a_400(self, client):
        assert client.patch("/api/v1/clock", json={}).status_code == 400

    def test_an_unparseable_time_is_a_400(self, client):
        assert client.patch("/api/v1/clock", json={"mock_current_time": "noon"}).status_code == 400

    def test_a_backend_without_a_clock_cannot_be_patched(self, client, srv):
        del srv.backend.market
        r = client.patch("/api/v1/clock", json={"paused": True})
        assert r.status_code == 400
        assert "no clock" in r.get_json()["error"]

    def test_setting_the_origin_snaps_to_nine_and_can_stay_paused(self, client, srv):
        r = client.put("/api/v1/clock/origin", json={
            "mock_init_time": "2025-09-03T11:22:00",
            "auto_start_progress": False, "auto_preload_data": False})
        assert r.get_json() == {"ok": True}
        t = srv.backend.market.get_market_time()
        assert t["mock_init_time"] == at(9, day=2)
        assert t["paused"] is True

    def test_setting_the_origin_with_preload_clears_the_loaded_bars(self, client, srv):
        srv.backend.market.historical_data["2330"] = {"data": None, "timestamps": None}
        r = client.put("/api/v1/clock/origin", json={
            "mock_init_time": at(9).isoformat(), "auto_start_progress": False})
        assert r.get_json() == {"ok": True}
        assert srv.backend.market.historical_data == {}
        assert srv._data_readiness == DataReadiness.ALL_SET

    @pytest.mark.parametrize("body", [{}, {"mock_init_time": "not-a-date"}])
    def test_a_missing_or_bad_origin_is_a_400(self, client, body):
        assert client.put("/api/v1/clock/origin", json=body).status_code == 400

    def test_a_failing_origin_is_reported_not_raised(self, srv):
        del srv.backend.market
        assert srv.set_timeline_origin(at(9)) is False


class TestTimelineRoute:
    def test_the_timeline_is_the_union_of_the_symbols_bars(self, client):
        r = client.get("/api/v1/clock/timeline?symbols=2330,2317"
                       "&start=2025-09-01T09:00:00&end=2025-09-01T09:04:00")
        assert r.get_json()["result"] == [at(9, m).isoformat() for m in (1, 2, 3)]

    def test_the_timeline_is_not_limited_by_the_clock(self, client):
        r = client.get("/api/v1/clock/timeline?symbols=2330"
                       "&start=2025-09-02T09:00:00&end=2025-09-02T09:02:00")
        assert r.get_json()["result"] == [at(9, 1, day=1).isoformat()]

    def test_symbols_are_required(self, client):
        assert client.get("/api/v1/clock/timeline?symbols= ,").status_code == 400

    def test_bad_dates_are_a_400(self, client):
        assert client.get("/api/v1/clock/timeline?symbols=2330&start=x&end=y").status_code == 400

    def test_a_source_failure_is_a_500_without_details(self, client, srv):
        srv.backend.data = _Source(fail=True)
        r = client.get("/api/v1/clock/timeline?symbols=2330"
                       "&start=2025-09-01&end=2025-09-02")
        assert r.status_code == 500
        assert "source down" not in r.get_data(as_text=True)


class TestMarketRoutes:
    def test_a_snapshot_reports_the_bar_at_the_clock(self, client):
        body = client.get("/api/v1/market/2330/snapshot").get_json()
        assert body["ok"] is True
        assert body["price"]["close"] == 100.0
        assert "warning" not in body

    def test_a_snapshot_warns_while_data_is_still_loading(self, client, srv):
        srv._data_readiness = DataReadiness.PREFETCHING
        assert "prefetching" in client.get("/api/v1/market/2330/snapshot").get_json()["warning"]

    def test_a_snapshot_failure_is_a_503(self, client, srv):
        def boom(_):
            raise RuntimeError("broker gone")
        srv.backend.snapshot = boom
        r = client.get("/api/v1/market/2330/snapshot")
        assert r.status_code == 503
        assert r.get_json()["error"] == "broker gone"

    def test_kbars_are_served_up_to_the_clock(self, client):
        body = client.get("/api/v1/market/2330/kbars?start=2025-09-01&end=2025-09-01").get_json()
        assert len(body["result"]) == 30
        assert "warning" not in body

    def test_kbars_warn_while_data_is_still_loading(self, client, srv):
        srv._data_readiness = DataReadiness.NONE
        body = client.get("/api/v1/market/2330/kbars?start=2025-09-01&end=2025-09-01").get_json()
        assert "none" in body["warning"]

    def test_an_unsupported_kbar_interval_is_a_400(self, client):
        r = client.get("/api/v1/market/2330/kbars?start=2025-09-01&end=2025-09-01&interval=3m")
        assert r.status_code == 400

    def test_a_kbar_source_failure_is_a_500(self, client, srv):
        srv.backend.data = _Source(fail=True)
        r = client.get("/api/v1/market/2330/kbars?start=2025-09-01&end=2025-09-01")
        assert r.status_code == 500

    def test_data_availability_without_a_broker(self, client):
        body = client.get("/api/v1/market/data-availability").get_json()
        assert body == {"ok": True, "source": "fake", "intervals": ["1m"],
                        "has_real_broker": False}

    def test_data_availability_with_a_broker_reports_its_range(self, client, srv):
        srv.backend.real_account = _Broker("sinopac")
        body = client.get("/api/v1/market/data-availability").get_json()
        assert body["broker"] == "sinopac"
        assert body["available_start"] == "2020-03-20"

    def test_a_broker_that_cannot_answer_is_a_500(self, client, srv):
        srv.backend.real_account = _Broker(fail=True)
        assert client.get("/api/v1/market/data-availability").status_code == 500


class TestDocs:
    def test_the_openapi_spec_lists_the_order_routes(self, client):
        spec = client.get("/openapi.json").get_json()
        assert "/api/v1/orders" in spec["paths"]
        assert "/api/v1/orders/{order_id}" in spec["paths"]


class TestPreloadData:
    def test_named_symbols_are_loaded(self, srv):
        assert srv._preload_data(["2330", "", "2317"], 2) == ["2317", "2330"]
        assert set(srv.backend.market.historical_data) >= {"2317", "2330"}

    def test_without_symbols_or_a_broker_nothing_is_loaded(self, srv):
        assert srv._preload_data(None, None) == []

    def test_without_symbols_the_brokers_positions_are_loaded(self, srv):
        holding = type("P", (), {"symbol": "2454"})()
        srv.backend.real_account = _Broker(positions=[holding])
        assert srv._preload_data(None, None) == ["2454"]
        assert "2454" in srv.backend.market.historical_data

    def test_a_backend_without_a_market_preloads_nothing(self, srv):
        del srv.backend.market
        assert srv._preload_data(["2330"], 1) == []


class TestSkipToTradingHours:
    def test_a_closed_market_jumps_to_the_next_open(self, srv):
        m = srv.backend.market
        m.resume_time_progress()
        m.start_date, m.real_init_time = at(14), datetime.now()
        srv._skip_to_trading_hours()
        now = m.get_market_time()["mock_current_time"]
        assert at(9, day=1) <= now < at(9, 1, day=1)

    def test_a_paused_clock_is_left_alone(self, srv):
        m = srv.backend.market
        m.set_market_time(at(14))
        srv._skip_to_trading_hours()
        assert m.manual_time_offset == timedelta(0)
        assert m.get_market_time()["mock_current_time"] == at(14)

    def test_reading_the_clock_skips_when_configured(self, client, srv):
        srv._skip_non_trading_hours = True
        calls = []
        srv._skip_to_trading_hours = lambda: calls.append(1)
        client.get("/api/v1/clock")
        assert calls == [1]


class TestMatchingLoop:
    def test_one_pass_matches_fills_and_expires_then_stops(self, client, srv):
        client.post("/api/v1/orders", json=_order_body())
        client.post("/api/v1/orders", json=_order_body(id="stale", price=50.0))
        srv.backend.market.set_market_time(at(13, 30))
        original = srv.backend.expire_resting_orders

        def expire_then_stop():
            out = original()
            srv._stop_event.set()
            return out
        srv.backend.expire_resting_orders = expire_then_stop
        t = threading.Thread(target=srv._matching_loop, daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()
        status = srv.backend.account_state.all_order_status
        assert status["client-id-1"].value == "FILLED"
        assert status["stale"].value == "CANCELLED"


class TestServerConstruction:
    def test_an_unknown_backend_name_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported backend_str"):
            ArenaX_BrokerSideServer(backend_str="nope", market_data=_Source(),
                                    price_db_path=str(tmp_path / "p.db"))

    def test_the_real_backend_needs_an_explicit_risk_acknowledgement(self, tmp_path, monkeypatch):
        monkeypatch.delenv("I_UNDERSTAND_REAL_TRADING_RISKS", raising=False)
        with pytest.raises(ValueError, match="I_UNDERSTAND_REAL_TRADING_RISKS"):
            ArenaX_BrokerSideServer(backend_str="real", market_data=_Source(),
                                    price_db_path=str(tmp_path / "p.db"))

    def test_a_given_backend_is_used_as_is(self, backend):
        srv = ArenaX_BrokerSideServer(backend=backend, port=0)
        assert srv.backend is backend
        assert srv.real is None
        assert srv._running is False


class TestRequireLoopback:
    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "::1"])
    def test_loopback_addresses_are_allowed(self, host):
        bss._require_loopback(host)

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
    def test_anything_else_is_refused(self, host):
        with pytest.raises(SystemExit, match="refusing to listen"):
            bss._require_loopback(host)


class TestFlag:
    @pytest.mark.parametrize("value", ["y", "YES", " true ", "1"])
    def test_truthy_spellings(self, value):
        assert bss._flag(value) is True

    @pytest.mark.parametrize("value", ["n", "no", "0", "", None, "maybe"])
    def test_everything_else_is_false(self, value):
        assert bss._flag(value) is False


class TestWerkzeugAccessFilter:
    def test_the_ip_and_timestamp_prefix_is_dropped(self):
        record = logging.LogRecord("werkzeug", logging.INFO, __file__, 1,
                                   '%s - - [%s] "%s" 200 -',
                                   ("127.0.0.1", "01/Sep/2025 09:00:00", "GET /health"), None)
        assert bss._WerkzeugAccessFilter().filter(record) is True
        assert record.msg == '"GET /health" 200 -'
        assert record.args is None


if __name__ == "__main__":
    pytest.main([__file__])
