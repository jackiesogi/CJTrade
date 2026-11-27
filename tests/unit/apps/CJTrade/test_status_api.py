"""The engine's status API serves the run's state to loopback callers holding the token.

Requests go through aiohttp's test server on an ephemeral 127.0.0.1 port. The
engine behind the view is fakes plus a real BotRegistry and RiskGate.
"""
from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.test_utils import TestServer
from cjtrade.apps.CJTrade import main as engine
from cjtrade.apps.CJTrade import protocol
from cjtrade.apps.CJTrade import status_api
from cjtrade.pkgs.risk import RiskGate
from cjtrade.pkgs.risk import RiskLimits

T0 = datetime(2026, 3, 2, 9, 1)
PORT = 12345                   # only ever a Host header; nothing binds it
HOST = f"127.0.0.1:{PORT}"
TOKEN = "run-token-123"


def bot_status(bot_id, seq):
    return protocol.BotStatus(
        bot_id=bot_id, seq=seq, bar_index=seq, market_time=T0 + timedelta(minutes=seq),
        started_at=T0, bars_seen=seq, bars_dropped=0, inflight={}, balance=1000.0,
        monitors={})


class FakeControlPlane:
    def __init__(self, state):
        self.state, self.calls = state, 0

    def get_backtest_state(self, session_id):
        self.calls += 1
        return self.state


FILLS = [
    {"time": "2026-03-02T09:01:00", "symbol": "2330", "action": "BUY", "quantity": 1, "price": 100},
    {"time": "2026-03-02T09:05:00", "symbol": "2330", "action": "SELL", "quantity": 1, "price": 110},
    {"time": "2026-03-02T09:02:00", "symbol": "2317", "action": "BUY", "quantity": 2, "price": 50},
    {"time": "2026-03-02T09:06:00", "symbol": "2317", "action": "SELL", "quantity": 2, "price": 45},
]


def make_view(curve=None, ctrl=None, stop_bot=None, clock=None, initial=1000.0):
    registry = engine.BotRegistry(history=10)
    for seq in range(3):
        registry.record(bot_status("Bot_A", seq), seq)
    gate = RiskGate(RiskLimits(max_notional_per_bot=500.0, max_orders_per_bar=3,
                               max_loss_pct=0.25, duplicate_window_bars=3),
                    initial_equity=initial)
    gate.record_submitted("Bot_A", "2330", "BUY", 2, 100.123, order_id="o1")
    cfg = engine.EngineConfig(broker="arenax", backend_mode="backtest",
                              symbols=["2330"], initial_balance=initial,
                              duration_days=30, playback_speed=60.0,
                              start_date="2026-03-02")
    if curve is None:
        curve = [{"time": f"2026-03-02T09:0{m}:00", "value": 1000.0 + 10 * m}
                 for m in range(1, 6)]
    return status_api.EngineView(
        session_id="sess-1", started_at=datetime.now(), cfg=cfg,
        clock_name="replay",
        clock=clock or SimpleNamespace(timestamps=[T0] * 4, finished=False),
        hub=SimpleNamespace(bars=2, market_time=T0),
        recorder=SimpleNamespace(initial_balance=initial, equity_curve=curve,
                                 start_time=T0.isoformat()),
        registry=registry, gate=gate,
        account_client=SimpleNamespace(control_plane=ctrl),
        bots=["Bot_A", "Bot_B"], stop_bot=stop_bot)


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    monkeypatch.delenv(status_api.CONTROL_TOKEN_ENV, raising=False)


def call(view, method, path, host=HOST, headers=None, **kw):
    """One request against build_app(view); returns (status, json)."""
    async def scenario():
        app = status_api.build_app(view, PORT)
        async with TestClient(TestServer(app)) as client:
            resp = await client.request(method, path,
                                        headers={"Host": host, **(headers or {})}, **kw)
            return resp.status, await resp.json()
    return asyncio.run(scenario())


def bearer(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Point:
    x: int
    at: datetime


class TestJsonable:
    def test_scalars_pass_through(self):
        assert [status_api._jsonable(v) for v in (None, True, 3, 1.5, "s")] == \
            [None, True, 3, 1.5, "s"]

    def test_datetimes_dataclasses_and_containers_become_json(self):
        value = {1: [Point(1, T0)], "s": {2}, "t": (T0,)}
        assert status_api._jsonable(value) == {
            "1": [{"x": 1, "at": T0.isoformat()}], "s": [2], "t": [T0.isoformat()]}

    def test_an_unknown_type_becomes_its_str_rather_than_failing(self):
        assert status_api._jsonable(Point) == str(Point)
        assert status_api._jsonable(object) == "<class 'object'>"


class TestViews:
    def test_a_replay_reports_how_far_through_its_bars_it_is(self):
        assert status_api._progress(make_view()) == {
            "clock": "replay", "bars_served": 2, "bars_total": 4, "fraction": 0.5,
            "market_time": T0.isoformat(), "finished": False}

    def test_a_live_clock_has_no_total_and_no_fraction(self):
        view = make_view(clock=engine.RealtimeClock())
        progress = status_api._progress(view)
        assert (progress["bars_total"], progress["fraction"], progress["finished"]) == \
            (None, None, False)

    def test_equity_is_the_last_sample_against_the_initial_balance(self):
        assert status_api._equity_block(make_view()) == {
            "initial": 1000.0, "current": 1050.0, "pnl": 50.0, "pnl_pct": 5.0,
            "samples": 5, "as_of": "2026-03-02T09:05:00"}

    def test_before_any_sample_there_is_no_current_equity(self):
        block = status_api._equity_block(make_view(curve=[]))
        assert (block["current"], block["pnl"], block["pnl_pct"], block["as_of"]) == \
            (None, None, None, None)

    def test_a_zero_initial_balance_has_no_percentage(self):
        assert status_api._equity_block(make_view(initial=0.0))["pnl_pct"] is None

    def test_risk_shows_the_limits_and_each_bots_rounded_exposure(self):
        assert status_api._risk_block(make_view()) == {
            "halted": False, "halt_reason": None,
            "limits": {"max_notional_per_bot": 500.0, "max_orders_per_bar": 3,
                       "max_loss_pct": 0.25, "duplicate_window_bars": 3},
            "exposure": {"Bot_A": 200.25}}

    def test_a_bot_that_never_reported_is_null_not_missing(self):
        bots = status_api._bot_block(make_view())
        assert bots["Bot_B"] is None and bots["Bot_A"]["seq"] == 2

    def test_a_stopped_bot_keeps_its_last_state_and_says_why(self):
        view = make_view()
        view.registry.mark_stopped("Bot_A", "bad fills")
        view.registry.mark_stopped("Bot_B", "never started")
        bots = status_api._bot_block(view)
        assert (bots["Bot_A"]["seq"], bots["Bot_A"]["stopped"],
                bots["Bot_A"]["stopped_reason"]) == (2, True, "bad fills")
        assert bots["Bot_B"] == {"stopped": True, "stopped_reason": "never started"}


class TestRoundTripCache:
    def test_a_broker_without_a_control_plane_says_it_is_unavailable(self):
        got = asyncio.run(status_api._RoundTripCache().get(make_view(ctrl=None)))
        assert (got["available"], got["round_trips"], got["cached"]) == (False, [], False)
        assert "no control plane" in got["reason"]

    def test_a_server_with_no_fill_history_says_so(self):
        got = asyncio.run(status_api._RoundTripCache().get(
            make_view(ctrl=FakeControlPlane(None))))
        assert (got["available"], got["reason"]) == \
            (False, "the server returned no fill history")

    def test_fills_are_matched_into_round_trips_with_a_win_rate(self):
        got = asyncio.run(status_api._RoundTripCache().get(
            make_view(ctrl=FakeControlPlane({"fill_history": FILLS}))))
        assert {k: got[k] for k in ("available", "fills", "closed", "wins",
                                    "losses", "win_rate_pct", "realised_pnl")} == \
            {"available": True, "fills": 4, "closed": 2, "wins": 1, "losses": 1,
             "win_rate_pct": 50.0, "realised_pnl": 0.0}
        assert [t["symbol"] for t in got["round_trips"]] == ["2330", "2317"]

    def test_no_closed_trades_has_no_win_rate(self):
        got = asyncio.run(status_api._RoundTripCache().get(
            make_view(curve=[], ctrl=FakeControlPlane({"fill_history": FILLS[:1]}))))
        assert (got["closed"], got["win_rate_pct"]) == (0, None)

    def test_a_second_ask_within_the_ttl_is_served_from_cache(self):
        ctrl = FakeControlPlane({"fill_history": FILLS})
        view = make_view(ctrl=ctrl)

        async def twice(cache):
            return await cache.get(view), await cache.get(view)
        first, second = asyncio.run(twice(status_api._RoundTripCache(ttl=60)))
        assert (first["cached"], second["cached"], ctrl.calls) == (False, True, 1)
        asyncio.run(twice(status_api._RoundTripCache(ttl=0)))
        assert ctrl.calls == 3


class TestLoopbackOnly:
    @pytest.mark.parametrize("host", [HOST, f"localhost:{PORT}", f"[::1]:{PORT}"])
    def test_each_loopback_name_on_this_port_is_answered(self, host):
        assert call(make_view(), "GET", "/health", host=host) == \
            (200, {"ok": True, "session_id": "sess-1", "bars_served": 2})

    @pytest.mark.parametrize("host", ["evil.example:12345", "127.0.0.1:8898",
                                      "127.0.0.1", "0.0.0.0:12345"])
    def test_any_other_host_header_is_refused(self, host):
        code, body = call(make_view(), "GET", "/health", host=host)
        assert code == 403 and "loopback Host" in body["error"]

    def test_no_cors_header_is_ever_sent(self):
        async def scenario():
            app = status_api.build_app(make_view(), PORT)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/status", headers={"Host": HOST,
                                                             "Origin": "http://evil"})
                return resp.headers
        assert "Access-Control-Allow-Origin" not in asyncio.run(scenario())


class TestTokenGate:
    def test_without_a_token_reads_are_open(self):
        assert call(make_view(), "GET", "/bots")[0] == 200

    def test_without_a_token_the_stop_route_refuses_rather_than_opening(self):
        calls = []

        async def stop(bot_id, reason):
            calls.append(bot_id)
            return {"ok": True}
        code, body = call(make_view(stop_bot=stop), "POST", "/bots/Bot_A/stop",
                          headers=bearer("anything"))
        assert code == 503 and status_api.CONTROL_TOKEN_ENV in body["error"]
        assert calls == []

    @pytest.mark.parametrize("headers", [{}, {"Authorization": TOKEN},
                                         {"Authorization": "Basic " + TOKEN},
                                         bearer("wrong"), bearer("")])
    def test_with_a_token_a_read_without_it_is_unauthorised(self, monkeypatch, headers):
        monkeypatch.setenv(status_api.CONTROL_TOKEN_ENV, TOKEN)
        code, body = call(make_view(), "GET", "/status", headers=headers)
        assert code == 401 and body["ok"] is False

    def test_with_a_token_a_read_carrying_it_is_answered(self, monkeypatch):
        monkeypatch.setenv(status_api.CONTROL_TOKEN_ENV, f"  {TOKEN}\n")
        assert call(make_view(), "GET", "/health", headers=bearer())[0] == 200

    def test_with_a_token_a_write_with_the_wrong_one_is_unauthorised(self, monkeypatch):
        monkeypatch.setenv(status_api.CONTROL_TOKEN_ENV, TOKEN)
        code, body = call(make_view(), "POST", "/bots/Bot_A/stop",
                          headers=bearer("wrong"))
        assert (code, body["error"]) == (401, "that control token is not this run's")


class TestReadRoutes:
    def test_status_carries_config_progress_equity_risk_and_bots(self):
        code, body = call(make_view(), "GET", "/status")
        assert code == 200
        assert body["session_id"] == "sess-1" and body["uptime_s"] >= 0
        assert body["config"] == {
            "broker": "arenax", "backend_mode": "backtest", "symbols": ["2330"],
            "requested_balance": 1000.0, "duration_days": 30,
            "playback_speed": 60.0, "start_date": "2026-03-02"}
        assert (body["progress"]["fraction"], body["equity"]["current"],
                body["risk"]["exposure"], sorted(body["bots"])) == \
            (0.5, 1050.0, {"Bot_A": 200.25}, ["Bot_A", "Bot_B"])

    def test_bots_lists_every_spawned_bot(self):
        code, body = call(make_view(), "GET", "/bots")
        assert code == 200 and body["Bot_B"] is None and body["Bot_A"]["bar_index"] == 2

    def test_a_bots_history_is_its_own_reports_oldest_first(self):
        view = make_view()
        view.registry.record(bot_status("Bot_B", 9), 3)
        code, body = call(view, "GET", "/bots/Bot_A/history")
        assert (code, body["bot_id"], body["kept"], body["capacity"]) == \
            (200, "Bot_A", 3, 10)
        assert [h["seq"] for h in body["history"]] == [0, 1, 2]

    def test_a_history_limit_keeps_the_newest(self):
        body = call(make_view(), "GET", "/bots/Bot_A/history?limit=2")[1]
        assert [h["seq"] for h in body["history"]] == [1, 2]

    def test_the_history_of_a_bot_not_in_this_run_is_not_found(self):
        code, body = call(make_view(), "GET", "/bots/Bot_Z/history")
        assert code == 404 and "Bot_Z" in body["error"]

    def test_the_equity_curve_is_tail_truncated_on_request(self):
        body = call(make_view(), "GET", "/equity?limit=2")[1]
        assert (body["samples"], body["returned"], body["truncated"]) == (5, 2, True)
        assert [p["value"] for p in body["curve"]] == [1040.0, 1050.0]
        assert (body["initial_balance"], body["start_time"]) == (1000.0, T0.isoformat())

    @pytest.mark.parametrize("query", ["", "?limit=0", "?limit=-3", "?limit=abc",
                                       "?limit="])
    def test_a_short_curve_comes_back_whole_whatever_the_limit_says(self, query):
        body = call(make_view(), "GET", f"/equity{query}")[1]
        assert (body["returned"], body["truncated"]) == (5, False)

    def test_the_default_equity_limit_truncates_a_long_curve(self):
        curve = [{"time": str(i), "value": i} for i in
                 range(status_api.DEFAULT_EQUITY_LIMIT + 5)]
        body = call(make_view(curve=curve), "GET", "/equity")[1]
        assert (body["returned"], body["truncated"], body["curve"][0]["value"]) == \
            (status_api.DEFAULT_EQUITY_LIMIT, True, 5)

    def test_roundtrips_are_served_over_http(self):
        code, body = call(make_view(ctrl=FakeControlPlane({"fill_history": FILLS})),
                          "GET", "/roundtrips")
        assert (code, body["closed"], body["cached"]) == (200, 2, False)

    def test_an_unknown_path_is_not_found(self):
        async def scenario():
            app = status_api.build_app(make_view(), PORT)
            async with TestClient(TestServer(app)) as client:
                return (await client.get("/nope", headers={"Host": HOST})).status
        assert asyncio.run(scenario()) == 404


class Stopper:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    async def __call__(self, bot_id, reason):
        self.calls.append((bot_id, reason))
        return {"ok": self.ok, "bot_id": bot_id, "at": T0}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv(status_api.CONTROL_TOKEN_ENV, TOKEN)


class TestStopRoute:
    def test_stopping_a_bot_passes_the_operators_reason(self, token):
        stopper = Stopper()
        code, body = call(make_view(stop_bot=stopper), "POST", "/bots/Bot_A/stop",
                          headers=bearer(), json={"reason": "bad fills"})
        assert (code, body) == (200, {"ok": True, "bot_id": "Bot_A",
                                      "at": T0.isoformat()})
        assert stopper.calls == [("Bot_A", "bad fills")]

    @pytest.mark.parametrize("kw", [{}, {"data": b"not json"}, {"json": {}},
                                    {"json": {"reason": ""}}])
    def test_no_usable_reason_falls_back_to_the_default(self, token, kw):
        stopper = Stopper()
        call(make_view(stop_bot=stopper), "POST", "/bots/Bot_A/stop",
             headers=bearer(), **kw)
        assert stopper.calls == [("Bot_A", "disabled by the operator")]

    def test_a_long_reason_is_cut_to_200_characters(self, token):
        stopper = Stopper()
        call(make_view(stop_bot=stopper), "POST", "/bots/Bot_A/stop",
             headers=bearer(), json={"reason": "x" * 500})
        assert len(stopper.calls[0][1]) == 200

    def test_a_stop_the_engine_refuses_is_a_bad_request(self, token):
        code, body = call(make_view(stop_bot=Stopper(ok=False)), "POST",
                          "/bots/Bot_A/stop", headers=bearer())
        assert code == 400 and body["ok"] is False

    def test_a_bot_not_in_this_run_is_not_found(self, token):
        stopper = Stopper()
        code, body = call(make_view(stop_bot=stopper), "POST", "/bots/Bot_Z/stop",
                          headers=bearer())
        assert code == 404 and body["bots"] == ["Bot_A", "Bot_B"]
        assert stopper.calls == []

    def test_an_engine_without_a_stop_hook_says_there_is_nothing_to_call(self, token):
        code, body = call(make_view(stop_bot=None), "POST", "/bots/Bot_A/stop",
                          headers=bearer())
        assert code == 503 and "stop hook" in body["error"]


class TestStart:
    @pytest.mark.parametrize("with_token", [False, True])
    def test_the_api_binds_to_loopback_only(self, monkeypatch, with_token):
        if with_token:
            monkeypatch.setenv(status_api.CONTROL_TOKEN_ENV, TOKEN)

        async def scenario():
            runner = await status_api.start(make_view(), 0)  # ephemeral port
            try:
                return [addr[0] for addr in runner.addresses]
            finally:
                await runner.cleanup()
        assert asyncio.run(scenario()) == ["127.0.0.1"]

    def test_a_port_already_taken_costs_the_api_not_the_run(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            assert asyncio.run(status_api.start(make_view(), port)) is None

    def test_the_host_is_loopback_and_not_configurable(self):
        assert status_api.STATUS_HOST == "127.0.0.1"
