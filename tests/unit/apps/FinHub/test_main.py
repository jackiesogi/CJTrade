"""Tests for FinHub.

Both upstreams are faked, so none of this needs a running engine or broker.
What that cannot cover is the contract itself — that the ArenaX server still
wants `order_lot: "IntraDayOdd"` and `type: "Stocks"`. Those live as named
constants in clients/arenax_client.py and are asserted here so a careless edit
to them fails something.
"""
import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("FINHUB_SECRET_KEY", "test-key-not-used-anywhere-real")
# FinHub keeps its database and run logs under cjtrade's data directory; point
# that somewhere disposable before anything is imported.
os.environ.setdefault("CJTRADE_HOME", tempfile.mkdtemp(prefix="finhub-test-"))
from cjtrade.apps.FinHub import main  # noqa: E402
from cjtrade.apps.FinHub.clients import BrokerError  # noqa: E402
from cjtrade.apps.FinHub.clients import EngineUnavailable  # noqa: E402
from cjtrade.apps.FinHub.clients import RunConfig  # noqa: E402
from cjtrade.apps.FinHub.clients import StrategyToolError  # noqa: E402
from cjtrade.apps.FinHub.clients import SupervisorError  # noqa: E402
from cjtrade.apps.FinHub.clients import arenax_client  # noqa: E402
from cjtrade.apps.FinHub.database import Base  # noqa: E402
from cjtrade.apps.FinHub.database import get_db  # noqa: E402

# One in-memory DB shared by every connection in the test process; the default
# in-memory SQLite gives each connection its own blank database.
_engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def _override_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


main.app.dependency_overrides[get_db] = _override_db


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=_engine)
    # The lifespan would start the run watcher and create tables on the real
    # engine, so it is skipped: these tests are about routes, not the daemon.
    with TestClient(main.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture(scope="module")
def authed(client):
    name = f"tester_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text
    res = client.post("/api/v1/auth/login",
                      data={"username": name, "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── auth is the gate on everything that touches money or processes ───────────

PROTECTED = [
    ("get", "/api/v1/engine/status"),
    ("get", "/api/v1/engine/bots"),
    ("get", "/api/v1/broker/account"),
    ("get", "/api/v1/broker/orders"),
    ("get", "/api/v1/runs"),
    ("get", "/api/v1/supervisor"),
    ("get", "/api/v1/audit"),
    ("get", "/api/v1/strategies"),
    ("get", "/api/v1/strategies/api-reference"),
    ("post", "/api/v1/runs"),
    ("post", "/api/v1/broker/orders"),
    ("post", "/api/v1/broker/orders/cancel-all"),
    # Writing a strategy is writing Python this host will execute. FinHub is a
    # single trust domain, so an account is permission to do that -- but not
    # having an account must not be.
    ("post", "/api/v1/strategies"),
    ("post", "/api/v1/strategies/check"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_sensitive_route_needs_a_token(client, method, path):
    """An unauthenticated POST /runs would spawn processes on the host, and an
    unauthenticated order route would trade."""
    res = (client.post(path, json={}) if method == "post"
           else client.get(path))
    assert res.status_code == 401, f"{method} {path} answered {res.status_code}"


def test_login_rejects_a_wrong_password(client, authed):
    res = client.post("/api/v1/auth/login",
                      data={"username": "nobody", "password": "wrong"})
    assert res.status_code == 401


# ── the engine being absent is normal, not an error ─────────────────────────

def test_engine_absent_is_a_200_not_a_502(client, authed, monkeypatch):
    """Most of the time there is no run. A 502 would have the UI render an
    error for the system's resting state."""
    async def boom(*a, **k):
        raise EngineUnavailable("connection refused")
    monkeypatch.setattr(main.engine_client, "status", boom)
    res = client.get("/api/v1/engine/status", headers=authed)
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_engine_status_is_passed_through_untouched(client, authed, monkeypatch):
    """Not re-modelled on purpose: a Pydantic mirror would drop any monitor
    field the strategy added until this file was edited too."""
    payload = {"session_id": "abc", "progress": {"bars_served": 7},
               "bots": {"Bot_C": {"monitors": {"something_new": 42}}}}

    async def ok(*a, **k):
        return payload
    monkeypatch.setattr(main.engine_client, "status", ok)
    body = client.get("/api/v1/engine/status", headers=authed).json()
    assert body["available"] is True
    assert body["status"]["bots"]["Bot_C"]["monitors"]["something_new"] == 42


def test_broker_unreachable_is_a_502_with_the_reason(client, authed, monkeypatch):
    async def boom(*a, **k):
        raise BrokerError("broker unreachable at http://127.0.0.1:8802")
    monkeypatch.setattr(main.broker_client, "account", boom)
    res = client.get("/api/v1/broker/account", headers=authed)
    assert res.status_code == 502
    assert "unreachable" in res.json()["detail"]


# ── the order payload must match what the broker parses ─────────────────────

def test_order_payload_matches_the_broker_contract():
    client_obj = arenax_client.ArenaXClient("http://127.0.0.1:1", "k")
    payload = client_obj.build_order("2317", "BUY", 80, 252.5, odd_lot=True)

    # The server requires all of these and 400s without them.
    for key in ("product", "action", "price", "quantity", "price_type",
                "order_type", "order_lot", "created_at", "id"):
        assert key in payload, key

    # ProductType.STOCK's *value* is "Stocks". Sending "STOCK" gets rejected.
    assert payload["product"]["type"] == "Stocks"
    assert payload["product"]["exchange"] == "TSE"
    # The only shape this broker path sends, matching ArenaXBrokerAPI_v2.
    assert payload["price_type"] == "LMT"
    assert payload["order_type"] == "ROD"
    assert payload["order_lot"] == "IntraDayOdd"
    assert len(payload["id"]) == 32          # uuid4 hex, the caller's own id


def test_common_lot_is_the_other_order_lot():
    client_obj = arenax_client.ArenaXClient("http://127.0.0.1:1", "k")
    payload = client_obj.build_order("2317", "SELL", 1000, 250.0, odd_lot=False)
    assert payload["order_lot"] == "Common"
    assert payload["action"] == "SELL"


def test_cancellable_statuses_match_the_shell():
    """The shell's `cancel` skips anything outside this set; a UI that tried to
    cancel a FILLED order would just collect errors."""
    assert "COMMITTED_WAIT_MATCHING" in arenax_client.CANCELLABLE
    assert "PARTIAL" in arenax_client.CANCELLABLE
    for resolved in ("FILLED", "CANCELLED", "REJECTED", "UNKNOWN"):
        assert resolved not in arenax_client.CANCELLABLE


# ── a manual order is acknowledged, recorded and tagged ─────────────────────

def test_a_manual_order_without_confirmation_is_refused(client, authed):
    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 10, "price": 100.0,
        "odd_lot": True, "confirm": False})
    assert res.status_code == 422
    assert "risk gate" in res.json()["detail"]


def test_a_manual_order_is_tagged_and_recorded(client, authed, monkeypatch):
    """Tagged because the engine filters its run report by session_id, so an
    untagged manual fill would be excluded from the report while still having
    moved the balance."""
    seen = {}

    async def fake_place(**kwargs):
        seen.update(kwargs)
        return {"order_id": "deadbeef" * 4, "status": "FILLED",
                "message": "Order filled.", "metadata": {}, "request": {}}
    monkeypatch.setattr(main.broker_client, "place_order", fake_place)

    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 80, "price": 252.5,
        "odd_lot": True, "confirm": True})
    assert res.status_code == 200, res.text
    assert seen["opt_field"]["source"] == "finhub-manual"
    assert "user" in seen["opt_field"]

    listed = client.get("/api/v1/broker/manual-orders", headers=authed).json()
    assert listed[0]["symbol"] == "2317"
    assert listed[0]["status"] == "FILLED"
    assert listed[0]["order_lot"] == "IntraDayOdd"

    audit = client.get("/api/v1/audit", headers=authed).json()
    assert any(row["action"] == "MANUAL_ORDER" for row in audit)


def test_a_broker_rejection_is_reported_not_raised(client, authed, monkeypatch):
    """The broker answering "no" is a verdict, and the reason is the useful
    part. A 500 here would hide it."""
    async def rejected(**kwargs):
        return {"order_id": "a" * 32, "status": "REJECTED",
                "message": "Insufficient balance", "metadata": {}, "request": {}}
    monkeypatch.setattr(main.broker_client, "place_order", rejected)
    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 999999, "price": 252.5,
        "odd_lot": True, "confirm": True})
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"
    assert res.json()["message"] == "Insufficient balance"


# ── RunConfig is where a run request is made safe ───────────────────────────

def _parse(**raw):
    return RunConfig.parse(raw, default_arenax_port=8802,
                           default_status_port=8898)


def test_run_config_accepts_a_sensible_request():
    cfg = _parse(symbols=["2317", "0050"], mode="backtest", days=20,
                 fund=1_000_000, speed=1, start_date="2026-09-01")
    assert cfg.symbols == ["2317", "0050"]
    assert cfg.arenax_port == 8802 and cfg.status_port == 8898


def test_run_config_takes_a_comma_string_too():
    assert _parse(symbols="2317, 2330 ").symbols == ["2317", "2330"]


@pytest.mark.parametrize("symbols", [
    [], ["../../etc/passwd"], ["2317; rm -rf /"], ["$(whoami)"], ["ab"],
    ["2317 2330"],
])
def test_run_config_refuses_anything_that_is_not_a_symbol(symbols):
    """No shell is involved in spawning, so this is not about shell injection.
    It is about not handing the engine something that cannot be a ticker and
    then debugging the result."""
    with pytest.raises(SupervisorError):
        _parse(symbols=symbols)


@pytest.mark.parametrize("kwargs", [
    {"days": 0}, {"days": 20000}, {"days": -5},
    {"fund": 1}, {"fund": 10 ** 12},
    {"speed": -1},
    {"mode": "real"}, {"mode": "nonsense"},
    {"start_date": "yesterday"},
])
def test_run_config_bounds_every_number(kwargs):
    """`days` becomes a replay length: an absurd one has the engine fetching
    bars for minutes before anything can interrupt it."""
    with pytest.raises(SupervisorError):
        _parse(symbols=["2317"], **kwargs)



def test_speed_zero_means_flat_out_and_is_allowed():
    """0 is how you ask for an unpaced replay. The engine honours the speed in
    backtest now, so without this there would be no way to ask for the
    behaviour every backtest had before the setting meant anything."""
    assert _parse(symbols=["2317"], speed=0).speed == 0


def test_a_paced_speed_survives_parsing():
    assert _parse(symbols=["2317"], speed=1200).speed == 1200.0


def test_run_config_allows_an_empty_start_date():
    """Empty means "take the server's own timeline origin" to the engine, which
    is different from any date FinHub could invent."""
    assert _parse(symbols=["2317"], start_date="").start_date == ""


def test_run_config_refuses_real_mode():
    """"real" is a CJTrade backend that trades an actual account. It is not on
    the list a web form can pick from."""
    with pytest.raises(SupervisorError):
        _parse(symbols=["2317"], mode="real")


# ── supervisor state ────────────────────────────────────────────────────────

def test_supervisor_starts_idle(client, authed):
    body = client.get("/api/v1/supervisor", headers=authed).json()
    assert body["busy"] is False
    assert body["run_id"] is None
    assert body["children"] == []


def test_a_broker_that_outlives_the_engine_is_not_a_run_in_flight():
    """`busy` used to mean "any child alive". The broker outlives the engine
    during teardown, so a finished run looked like it was still going: its row
    never got a summary and the next run was refused as a conflict."""
    import subprocess

    from cjtrade.apps.FinHub.clients import supervisor as sup_mod

    sup = main.supervisor
    sup._children = []
    fake_broker = sup_mod.Child(name="broker", argv=[],
                                popen=subprocess.Popen(["sleep", "30"]),
                                log_path=main.settings.RUN_LOG_DIR / "x.log")
    dead_engine = sup_mod.Child(name="engine", argv=[],
                                popen=subprocess.Popen(["true"]),
                                log_path=main.settings.RUN_LOG_DIR / "x.log")
    dead_engine.popen.wait()
    sup._children = [fake_broker, dead_engine]
    try:
        assert sup.broker_alive is True
        assert sup.engine_started is True
        assert sup.engine_alive is False
        assert sup.busy is False          # the run is over
        assert sup.engine_exit() == 0     # readable after the process is gone
    finally:
        fake_broker.popen.kill()
        sup._children = []


def test_a_run_whose_engine_has_not_spawned_yet_is_not_finished():
    """Starting a run sets the run id, then waits for the broker. Treating that
    window as "the engine has exited" finalised runs before they began."""
    import subprocess

    from cjtrade.apps.FinHub.clients import supervisor as sup_mod

    sup = main.supervisor
    sup._children = []
    broker = sup_mod.Child(name="broker", argv=[],
                           popen=subprocess.Popen(["sleep", "30"]),
                           log_path=main.settings.RUN_LOG_DIR / "x.log")
    sup._children = [broker]
    try:
        assert sup.engine_started is False
        assert sup.engine_alive is False
        assert sup.engine_exit() is None
    finally:
        broker.popen.kill()
        sup._children = []


def test_a_run_whose_processes_cannot_start_fails_cleanly(client, authed,
                                                           monkeypatch, tmp_path):
    """An interpreter that cannot be run should be a 409 that names it, not a
    traceback and a half-started run."""
    async def broker_down():
        return False
    monkeypatch.setattr(main.supervisor, "python", str(tmp_path / "not-here"))
    monkeypatch.setattr(main.supervisor, "_client_factory",
                        lambda *a: type("C", (), {"is_up": staticmethod(broker_down)})())
    res = client.post("/api/v1/runs", headers=authed,
                      json={"symbols": ["2317"], "mode": "backtest", "days": 5})
    assert res.status_code == 409
    assert "could not start" in res.json()["detail"]

    # The Run row still exists, marked failed, with the reason on it: a run
    # that never started is still something you want to see in the list.
    runs = client.get("/api/v1/runs", headers=authed).json()
    assert runs[0]["status"] == "failed"
    assert "not-here" in runs[0]["error"]


def test_a_run_log_for_a_run_that_never_started(client, authed):
    runs = client.get("/api/v1/runs", headers=authed).json()
    res = client.get(f"/api/v1/runs/{runs[0]['id']}/log", headers=authed)
    assert res.status_code == 200
    assert "never got as far" in res.text


def test_another_users_run_is_a_404(client, authed):
    res = client.get("/api/v1/runs/999999", headers=authed)
    assert res.status_code == 404


# ── pages ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/dashboard", "/runs", "/bots",
                                  "/positions", "/orders", "/market",
                                  "/trade", "/audit"])
def test_known_pages_serve_the_shell(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert "CJTrade Console" in res.text


def test_an_unknown_page_is_a_404_not_a_blank_dashboard(client):
    """A typo that silently rendered the dashboard looks like a bug in the
    page rather than a bad URL."""
    res = client.get("/not-a-page")
    assert res.status_code == 404


# ── strategies ───────────────────────────────────────────────────────────────
#
# The checker is a subprocess in the CJTrade checkout, so it is faked here:
# these tests are about the routes, ownership and what gets stored, and a test
# suite that shells out to another repository would fail for reasons that have
# nothing to do with FinHub. That the checker itself works is CJTrade's to
# prove (tests/unit/pkgs/strategy/).

TEMPLATE = ('"""%s — %s"""\n'
            'from cjtrade.pkgs.strategy.authoring import *\n\n\n'
            'def on_bar(bar, account):\n    return hold("stub")\n')


@pytest.fixture
def fake_checker(monkeypatch):
    """Stand in for the CJTrade subprocess, and record what it was asked."""
    calls = {"template": [], "check": [], "api": 0, "templates": 0}

    def template(name, symbol, kind="bb"):
        calls["template"].append((name, symbol, kind))
        return TEMPLATE % (name, symbol)

    def templates():
        calls["templates"] += 1
        return [{"kind": "bb", "label": "Bollinger", "note": "bot_c"},
                {"kind": "dca", "label": "DCA", "note": "bot_a"},
                {"kind": "adx", "label": "Regime", "note": "bot_b"}]

    def check(source):
        calls["check"].append(source)
        if "def on_bar(bar, account)" in source:
            return {"ok": True, "diagnostics": [],
                    "params": [{"kind": "int", "default": 20,
                                "label": "Window", "min": 2}]}
        return {"ok": False, "params": [], "diagnostics": [
            {"message": "a strategy needs a function called on_bar(bar, account)",
             "line": 1, "offset": 1, "severity": "error"}]}

    def api_reference():
        calls["api"] += 1
        return [{"name": "buy", "qualified": "buy", "kind": "function",
                 "signature": "buy(shares=None)", "doc": "Ask to buy."}]

    monkeypatch.setattr(main.strategy_tool, "template", template)
    monkeypatch.setattr(main.strategy_tool, "templates", templates)
    monkeypatch.setattr(main.strategy_tool, "check", check)
    monkeypatch.setattr(main.strategy_tool, "api_reference", api_reference)
    return calls


def _new_strategy(client, authed, **kwargs):
    body = {"name": "Fade the band", "symbol": "2330"}
    body.update(kwargs)
    res = client.post("/api/v1/strategies", json=body, headers=authed)
    assert res.status_code == 201, res.text
    return res.json()


def test_a_new_strategy_is_prefilled_with_the_name_and_symbol(
        client, authed, fake_checker):
    """A blank editor is the worst place to learn an API from, so the server
    fills one in -- and the template comes from CJTrade, not from FinHub."""
    created = _new_strategy(client, authed)
    assert created["name"] == "Fade the band"
    assert created["symbol"] == "2330"
    assert "Fade the band — 2330" in created["source"]
    assert fake_checker["template"] == [("Fade the band", "2330", "bb")]


def test_the_requested_template_is_the_one_used(client, authed, fake_checker):
    _new_strategy(client, authed, kind="dca")
    assert fake_checker["template"][-1][2] == "dca"


def test_the_template_list_comes_from_the_checkout(client, authed,
                                                   fake_checker):
    body = client.get("/api/v1/strategies/templates", headers=authed).json()
    assert [t["kind"] for t in body["templates"]] == ["bb", "dca", "adx"]


def test_templates_is_not_shadowed_by_the_id_route(client, authed,
                                                   fake_checker):
    """Same hazard as api-reference: "templates" must not parse as an id."""
    res = client.get("/api/v1/strategies/templates", headers=authed)
    assert res.status_code == 200, res.text


def test_a_supplied_source_is_not_overwritten(client, authed, fake_checker):
    created = _new_strategy(client, authed, source="# mine\n")
    assert created["source"] == "# mine\n"
    assert fake_checker["template"] == []


def test_a_new_strategy_has_no_verdict_yet(client, authed, fake_checker):
    """Three states, not two: never checked is not the same as checked and
    broken, and a tick on unchecked text would be a lie."""
    assert _new_strategy(client, authed)["last_check_ok"] is None


def test_symbols_are_normalised(client, authed, fake_checker):
    assert _new_strategy(client, authed, symbol=" 0050 ")["symbol"] == "0050"


@pytest.mark.parametrize("symbol", ["", "2317 2330", "../etc/passwd",
                                    "2317;rm", "a" * 13])
def test_a_symbol_that_is_not_a_symbol_is_refused(client, authed, fake_checker,
                                                  symbol):
    res = client.post("/api/v1/strategies",
                      json={"name": "x", "symbol": symbol}, headers=authed)
    assert res.status_code == 422, f"{symbol!r} was accepted"


def test_checking_stores_the_verdict_so_the_list_can_show_it(
        client, authed, fake_checker):
    created = _new_strategy(client, authed)
    res = client.post(f"/api/v1/strategies/{created['id']}/check",
                      headers=authed)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert res.json()["params"][0]["label"] == "Window"

    listed = client.get("/api/v1/strategies", headers=authed).json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["last_check_ok"] == 1
    assert row["last_check_error"] is None
    assert "source" not in row         # the list is not twenty files


def test_a_broken_strategy_records_the_first_problem(client, authed,
                                                     fake_checker):
    created = _new_strategy(client, authed, source="x = 1\n")
    res = client.post(f"/api/v1/strategies/{created['id']}/check",
                      headers=authed)
    assert res.json()["ok"] is False
    stored = client.get(f"/api/v1/strategies/{created['id']}",
                        headers=authed).json()
    assert stored["last_check_ok"] == 0
    assert "on_bar" in stored["last_check_error"]


def test_a_source_full_of_errors_is_still_a_200(client, authed, fake_checker):
    """"This does not compile" is a successful answer to the question asked,
    and the editor needs the diagnostics in the body either way."""
    res = client.post("/api/v1/strategies/check", json={"source": "x = 1\n"},
                      headers=authed)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False
    assert res.json()["diagnostics"][0]["line"] == 1


def test_a_checker_that_cannot_run_is_a_502(client, authed, monkeypatch):
    """Distinct from a broken strategy. One is the user's problem, the other
    is the deployment's, and the editor says different things about them."""
    def explode(_source):
        raise StrategyToolError("cannot run 'uv' — is uv on FinHub's PATH?")
    monkeypatch.setattr(main.strategy_tool, "check", explode)
    res = client.post("/api/v1/strategies/check", json={"source": "x = 1\n"},
                      headers=authed)
    assert res.status_code == 502
    assert "uv" in res.json()["detail"]


def test_editing_the_source_clears_a_stale_verdict(client, authed,
                                                   fake_checker):
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/check", headers=authed)
    res = client.put(f"/api/v1/strategies/{created['id']}",
                     json={"source": "# changed\n"}, headers=authed)
    assert res.status_code == 200, res.text
    assert res.json()["last_check_ok"] is None
    assert res.json()["last_check_error"] is None


def test_renaming_does_not_clear_the_verdict(client, authed, fake_checker):
    """The verdict is about the source, and a rename does not touch it."""
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/check", headers=authed)
    res = client.put(f"/api/v1/strategies/{created['id']}",
                     json={"name": "Renamed"}, headers=authed)
    assert res.json()["name"] == "Renamed"
    assert res.json()["last_check_ok"] == 1


def test_saving_the_same_source_leaves_the_verdict_alone(client, authed,
                                                         fake_checker):
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/check", headers=authed)
    res = client.put(f"/api/v1/strategies/{created['id']}",
                     json={"source": created["source"]}, headers=authed)
    assert res.json()["last_check_ok"] == 1


def test_another_users_strategy_is_a_404_not_a_403(client, fake_checker):
    """A 403 would confirm that the strategy exists and belongs to someone
    else, which this endpoint has no reason to tell anyone."""
    def account():
        name = f"owner_{uuid.uuid4().hex[:8]}"
        client.post("/api/v1/auth/register", json={
            "username": name, "email": f"{name}@example.com",
            "password": "a-long-enough-password"})
        token = client.post("/api/v1/auth/login", data={
            "username": name, "password": "a-long-enough-password"
        }).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    mine, theirs = account(), account()
    created = _new_strategy(client, mine)

    for call in (lambda: client.get(f"/api/v1/strategies/{created['id']}",
                                    headers=theirs),
                 lambda: client.put(f"/api/v1/strategies/{created['id']}",
                                    json={"name": "stolen"}, headers=theirs),
                 lambda: client.delete(f"/api/v1/strategies/{created['id']}",
                                       headers=theirs),
                 lambda: client.post(f"/api/v1/strategies/{created['id']}/check",
                                     headers=theirs)):
        res = call()
        assert res.status_code == 404, res.text

    # And it is untouched.
    still = client.get(f"/api/v1/strategies/{created['id']}",
                       headers=mine).json()
    assert still["name"] == "Fade the band"
    # Their list has their own seeded examples and nothing of mine.
    theirs_ids = [s["id"] for s in
                  client.get("/api/v1/strategies", headers=theirs).json()]
    assert created["id"] not in theirs_ids


def test_deleting_removes_it(client, authed, fake_checker):
    created = _new_strategy(client, authed)
    assert client.delete(f"/api/v1/strategies/{created['id']}",
                         headers=authed).status_code == 204
    assert client.get(f"/api/v1/strategies/{created['id']}",
                      headers=authed).status_code == 404


def test_api_reference_is_not_shadowed_by_the_id_route(client, authed,
                                                       fake_checker):
    """`/strategies/api-reference` must not be read as strategy id
    "api-reference"; it is declared first for exactly that reason."""
    res = client.get("/api/v1/strategies/api-reference", headers=authed)
    assert res.status_code == 200, res.text
    assert res.json()["entries"][0]["name"] == "buy"
    assert fake_checker["api"] == 1


def test_a_missing_api_reference_does_not_break_the_editor(client, authed,
                                                           monkeypatch):
    """The editor still has CodeMirror's own Python completion without it, so
    this is an empty list with a reason rather than a 500."""
    def explode():
        raise StrategyToolError("the strategy checker failed")
    monkeypatch.setattr(main.strategy_tool, "api_reference", explode)
    res = client.get("/api/v1/strategies/api-reference", headers=authed)
    assert res.status_code == 200
    assert res.json()["entries"] == []
    # Said, but not with the tool's own error text: that stays in the log.
    assert res.json()["error"] == main.TOOL_DOWN


def test_an_oversized_source_is_refused_before_it_reaches_a_subprocess(
        client, authed):
    res = client.post("/api/v1/strategies/check",
                      json={"source": "#" * 300_000}, headers=authed)
    assert res.status_code == 422


def test_the_editor_page_serves_the_shell(client):
    assert client.get("/editor").status_code == 200


# ── the bots page ────────────────────────────────────────────────────────────
#
# /api/v1/engine/bots is the engine's live view and empty between runs, so a
# strategy somebody had just written was invisible until a run happened to be
# in flight. /api/v1/bots is the composed answer: what bots exist, and which
# of them are alive.


def _fake_live(monkeypatch, bots):
    async def live():
        return bots
    monkeypatch.setattr(main.engine_client, "bots", live)


def _no_engine(monkeypatch):
    async def live():
        raise EngineUnavailable("no run in flight")
    monkeypatch.setattr(main.engine_client, "bots", live)


def test_a_saved_strategy_appears_with_no_run_in_flight(client, authed,
                                                        fake_checker,
                                                        monkeypatch):
    _no_engine(monkeypatch)
    created = _new_strategy(client, authed, name="Idle one", symbol="2454")
    body = client.get("/api/v1/bots", headers=authed).json()

    assert body["engine_available"] is False
    entry = next(b for b in body["bots"] if b["strategy_id"] == created["id"])
    assert (entry["kind"], entry["name"], entry["symbol"]) == (
        "strategy", "Idle one", "2454")
    assert entry["live"] is False
    assert entry["bot_id"] is None
    assert entry["status"] is None


def test_the_check_state_rides_along_so_the_card_can_show_it(
        client, authed, fake_checker, monkeypatch):
    _no_engine(monkeypatch)
    created = _new_strategy(client, authed)
    before = _bot_entry(client, authed, created["id"])
    assert before["check_ok"] is None          # never checked

    client.post(f"/api/v1/strategies/{created['id']}/check", headers=authed)
    after = _bot_entry(client, authed, created["id"])
    assert after["check_ok"] == 1
    assert after["check_error"] is None


def _bot_entry(client, authed, strategy_id):
    body = client.get("/api/v1/bots", headers=authed).json()
    return next(b for b in body["bots"] if b["strategy_id"] == strategy_id)


def test_deleting_the_strategy_removes_it_from_the_bots_page(
        client, authed, fake_checker, monkeypatch):
    _no_engine(monkeypatch)
    created = _new_strategy(client, authed, name="Short lived")
    assert _bot_entry(client, authed, created["id"])["name"] == "Short lived"

    assert client.delete(f"/api/v1/strategies/{created['id']}",
                         headers=authed).status_code == 204
    body = client.get("/api/v1/bots", headers=authed).json()
    assert all(b["strategy_id"] != created["id"] for b in body["bots"])
    assert all(b["name"] != "Short lived" for b in body["bots"])


def test_a_live_bot_with_no_strategy_of_yours_is_still_listed(
        client, authed, monkeypatch):
    """The engine ships built-in bots, and a bot that is trading must never be
    missing from the page that shows bots."""
    _fake_live(monkeypatch, {"Bot_C": {"bar_index": 42, "balance": 99_000.0,
                                       "monitors": {"regime": "tradeable"}}})
    body = client.get("/api/v1/bots", headers=authed).json()
    entry = next(b for b in body["bots"] if b["bot_id"] == "Bot_C")
    assert entry["kind"] == "engine"
    assert entry["live"] is True
    assert entry["status"]["bar_index"] == 42
    assert entry["strategy_id"] is None


def test_a_live_bot_is_matched_to_the_strategy_it_is_running(
        client, authed, fake_checker, monkeypatch):
    created = _new_strategy(client, authed, name="Running one", symbol="2317")
    bot_id = f"Bot_{uuid.uuid4().hex[:6]}"
    _run_with_slot(client, authed, bot_id=bot_id, strategy_id=created["id"],
                   strategy="Running one", symbol="2317")
    _fake_live(monkeypatch, {bot_id: {"bar_index": 7, "balance": 1.0,
                                      "monitors": {}}})

    body = client.get("/api/v1/bots", headers=authed).json()
    entry = next(b for b in body["bots"] if b["strategy_id"] == created["id"])
    assert entry["live"] is True
    assert entry["bot_id"] == bot_id
    assert entry["status"]["bar_index"] == 7
    # And it is not listed twice, once as a strategy and once as an engine bot.
    assert sum(1 for b in body["bots"] if b["bot_id"] == bot_id) == 1


def test_deleting_a_strategy_keeps_the_record_of_the_run_that_used_it(
        client, authed, fake_checker, monkeypatch):
    """Off the bots page, but not erased: the slot is the record that a run
    happened, so it has to outlive the source it ran."""
    created = _new_strategy(client, authed, name="Was run once")
    bot_id = f"Bot_{uuid.uuid4().hex[:6]}"
    run_id = _run_with_slot(client, authed, bot_id=bot_id,
                            strategy_id=created["id"],
                            strategy="Was run once", symbol="2317")
    client.delete(f"/api/v1/strategies/{created['id']}", headers=authed)

    with _Session() as db:
        slot = db.query(main.models.BotSlot).filter(
            main.models.BotSlot.run_id == run_id).one()
        assert slot.strategy_id is None          # de-associated, not deleted
        assert slot.strategy == "Was run once"   # still readable

    # And a live bot on that id is labelled by the name recorded at launch.
    _fake_live(monkeypatch, {bot_id: {"bar_index": 1, "balance": 1.0,
                                      "monitors": {}}})
    body = client.get("/api/v1/bots", headers=authed).json()
    entry = next(b for b in body["bots"] if b["bot_id"] == bot_id)
    assert entry["kind"] == "engine"
    assert entry["name"] == "Was run once"


def test_one_users_strategies_are_not_on_another_users_bots_page(
        client, fake_checker, monkeypatch):
    _no_engine(monkeypatch)

    def account():
        name = f"botpage_{uuid.uuid4().hex[:8]}"
        client.post("/api/v1/auth/register", json={
            "username": name, "email": f"{name}@example.com",
            "password": "a-long-enough-password"})
        token = client.post("/api/v1/auth/login", data={
            "username": name, "password": "a-long-enough-password"
        }).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    mine, theirs = account(), account()
    created = _new_strategy(client, mine, name="Only mine")
    body = client.get("/api/v1/bots", headers=theirs).json()
    assert all(b["strategy_id"] != created["id"] for b in body["bots"])


def _run_with_slot(client, authed, *, bot_id, strategy_id, strategy, symbol):
    """A finished run with one bot slot, written straight to the DB.

    Going through POST /runs would spawn processes; what is being tested here
    is the join between a slot and a strategy, which does not need a run to
    have actually happened.
    """
    me = client.get("/api/v1/auth/me", headers=authed).json()
    with _Session() as db:
        run = main.models.Run(owner_id=me["id"], status="finished",
                         symbols=symbol, mode="backtest")
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(main.models.BotSlot(run_id=run.id, bot_id=bot_id, strategy=strategy,
                              symbol=symbol, strategy_id=strategy_id))
        db.commit()
        return run.id


# ── enable / disable ─────────────────────────────────────────────────────────
#
# Off has to mean off *now*. Somebody pressing it during a paper or real run
# has just found a problem, and "it will not be in the next run" is not an
# answer, so the engine grew a control plane and this is the half that drives
# it. Off must never be read as "and sell what it holds": that is a second
# decision, made at whatever price happens to be there.


@pytest.fixture
def fake_engine_stop(monkeypatch):
    """Stand in for the engine's control plane, and record the calls."""
    calls = []

    async def stop_bot(bot_id, reason):
        calls.append((bot_id, reason))
        return {"ok": True, "bot_id": bot_id, "reason": reason,
                "orders_cancelled": ["abc123"], "position_flattened": False}

    monkeypatch.setattr(main.engine_client, "stop_bot", stop_bot)
    return calls


def _pretend_running(monkeypatch, mapping):
    """Make the supervisor look like it is running `mapping` right now."""
    monkeypatch.setattr(type(main.supervisor), "bot_strategies",
                        property(lambda self: mapping))
    monkeypatch.setattr(type(main.supervisor), "control_token",
                        property(lambda self: "a-token"))


def test_a_new_strategy_is_enabled(client, authed, fake_checker):
    assert _new_strategy(client, authed)["enabled"] is True


def test_disabling_between_runs_just_sets_the_flag(client, authed,
                                                   fake_checker,
                                                   fake_engine_stop):
    created = _new_strategy(client, authed)
    res = client.post(f"/api/v1/strategies/{created['id']}/enabled",
                      json={"enabled": False}, headers=authed)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is False
    assert body["stopped_now"] is False
    assert fake_engine_stop == []          # nothing was running to stop
    assert client.get(f"/api/v1/strategies/{created['id']}",
                      headers=authed).json()["enabled"] is False


def test_disabling_a_live_strategy_stops_its_bot_now(client, authed,
                                                     fake_checker,
                                                     fake_engine_stop,
                                                     monkeypatch):
    created = _new_strategy(client, authed, name="Misbehaving")
    _pretend_running(monkeypatch, {
        "Bot_S1": {"strategy_id": created["id"], "name": "Misbehaving",
                   "symbol": "2330"}})

    body = client.post(f"/api/v1/strategies/{created['id']}/enabled",
                       json={"enabled": False}, headers=authed).json()
    assert body["stopped_now"] is True
    assert body["bot_id"] == "Bot_S1"
    assert len(fake_engine_stop) == 1
    bot_id, reason = fake_engine_stop[0]
    assert bot_id == "Bot_S1"
    assert "Misbehaving" in reason          # the log should say which one
    # And the answer makes clear what was NOT done.
    assert body["engine"]["position_flattened"] is False


def test_a_stop_that_fails_is_reported_loudly(client, authed, fake_checker,
                                              monkeypatch):
    """The flag is off either way, so the next run is safe. What failed is the
    urgent half, and somebody who pressed this believes trading has stopped."""
    created = _new_strategy(client, authed)
    _pretend_running(monkeypatch, {
        "Bot_S1": {"strategy_id": created["id"], "name": created["name"],
                   "symbol": "2330"}})

    async def explode(bot_id, reason):
        raise EngineUnavailable("the engine is not answering")
    monkeypatch.setattr(main.engine_client, "stop_bot", explode)

    body = client.post(f"/api/v1/strategies/{created['id']}/enabled",
                       json={"enabled": False}, headers=authed).json()
    assert body["enabled"] is False        # the flag still changed
    assert body["stopped_now"] is False
    assert "could NOT be stopped" in body["error"]
    assert "not answering" not in body["error"], "the upstream error stays in the log"


def test_enabling_does_not_pretend_to_start_a_bot(client, authed,
                                                  fake_checker,
                                                  fake_engine_stop):
    """The engine builds its roster when a run starts, so a re-enabled
    strategy joins the next one -- it does not appear mid-run."""
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/enabled",
                json={"enabled": False}, headers=authed)
    body = client.post(f"/api/v1/strategies/{created['id']}/enabled",
                       json={"enabled": True}, headers=authed).json()
    assert body["enabled"] is True
    assert body["stopped_now"] is False
    assert fake_engine_stop == []


def test_disabling_is_audited(client, authed, fake_checker, fake_engine_stop):
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/enabled",
                json={"enabled": False}, headers=authed)
    actions = [a["action"] for a in
               client.get("/api/v1/audit", headers=authed).json()]
    assert "strategy.disable" in actions


def test_another_users_strategy_cannot_be_switched_off(client, fake_checker):
    def account():
        name = f"toggler_{uuid.uuid4().hex[:8]}"
        client.post("/api/v1/auth/register", json={
            "username": name, "email": f"{name}@example.com",
            "password": "a-long-enough-password"})
        token = client.post("/api/v1/auth/login", data={
            "username": name, "password": "a-long-enough-password"
        }).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    mine, theirs = account(), account()
    created = _new_strategy(client, mine)
    res = client.post(f"/api/v1/strategies/{created['id']}/enabled",
                      json={"enabled": False}, headers=theirs)
    assert res.status_code == 404
    assert client.get(f"/api/v1/strategies/{created['id']}",
                      headers=mine).json()["enabled"] is True


def test_a_disabled_strategy_shows_as_off_on_the_bots_page(
        client, authed, fake_checker, fake_engine_stop, monkeypatch):
    _no_engine(monkeypatch)
    created = _new_strategy(client, authed)
    client.post(f"/api/v1/strategies/{created['id']}/enabled",
                json={"enabled": False}, headers=authed)
    assert _bot_entry(client, authed, created["id"])["enabled"] is False


# ── seeding the examples ─────────────────────────────────────────────────────


def test_registering_seeds_the_example_strategies(client, fake_checker):
    """A blank editor is the worst place to learn an API from, so a new
    account starts with the three the engine's built-in bots run."""
    name = f"fresh_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text
    token = client.post("/api/v1/auth/login", data={
        "username": name, "password": "a-long-enough-password"
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/v1/strategies", headers=headers).json()
    assert {s["seeded_from"] for s in listed} == {"bb", "dca", "adx"}
    assert {s["symbol"] for s in listed} == {"2317", "0050", "2357"}
    assert all(s["enabled"] for s in listed)


def test_deleting_a_seeded_example_keeps_it_deleted(client, fake_checker):
    """Without the per-template marker, deleting one would have it reappear on
    the next request, which is a page that will not let you throw things away."""
    name = f"tidy_{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    token = client.post("/api/v1/auth/login", data={
        "username": name, "password": "a-long-enough-password"
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/v1/strategies", headers=headers).json()
    doomed = next(s for s in listed if s["seeded_from"] == "dca")
    client.delete(f"/api/v1/strategies/{doomed['id']}", headers=headers)

    after = client.get("/api/v1/strategies", headers=headers).json()
    assert {s["seeded_from"] for s in after} == {"bb", "adx"}


def test_restoring_examples_brings_back_only_what_is_missing(client,
                                                             fake_checker):
    name = f"restorer_{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    token = client.post("/api/v1/auth/login", data={
        "username": name, "password": "a-long-enough-password"
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/v1/strategies", headers=headers).json()
    doomed = next(s for s in listed if s["seeded_from"] == "adx")
    client.delete(f"/api/v1/strategies/{doomed['id']}", headers=headers)

    body = client.post("/api/v1/strategies/seed-examples",
                       headers=headers).json()
    assert [s["kind"] for s in body["created"]] == ["adx"]
    # Asking again makes nothing: the other two are already there.
    assert client.post("/api/v1/strategies/seed-examples",
                       headers=headers).json()["created"] == []


def test_a_checkout_that_cannot_make_templates_does_not_block_registering(
        client, monkeypatch):
    """Seeding is a convenience, not a prerequisite."""
    def explode(name, symbol, kind="bb"):
        raise StrategyToolError("no checkout")
    monkeypatch.setattr(main.strategy_tool, "template", explode)

    name = f"nocheckout_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text


# ── the price on the bot chart ───────────────────────────────────────────────
#
# The chart draws whatever a strategy asked to have plotted, and the price
# underneath it always. Indicator values with no price to read them against
# are unreadable, and the bot is the process that has the number the strategy
# actually saw -- FinHub only has to not drop it.


def test_the_price_reaches_the_bots_page(client, authed, monkeypatch):
    _fake_live(monkeypatch, {"Bot_S1": {
        "bar_index": 42, "balance": 99_000.0, "close": 254.5,
        "plots": {"upper": 255.0, "lower": 254.0},
        "monitors": {"last_decision": "inside the bands"}}})
    entry = next(b for b in client.get("/api/v1/bots", headers=authed).json()
                 ["bots"] if b["bot_id"] == "Bot_S1")
    assert entry["status"]["close"] == 254.5
    assert entry["status"]["plots"] == {"upper": 255.0, "lower": 254.0}


def test_an_engine_that_reports_no_price_is_not_invented(client, authed,
                                                         monkeypatch):
    """A bot that has not seen a bar has no price, and a zero would be drawn
    as a real one. The page has to be able to tell the difference."""
    _fake_live(monkeypatch, {"Bot_S1": {"bar_index": 0, "balance": 1.0,
                                        "monitors": {}}})
    entry = next(b for b in client.get("/api/v1/bots", headers=authed).json()
                 ["bots"] if b["bot_id"] == "Bot_S1")
    assert "close" not in entry["status"] or not entry["status"]["close"]



@pytest.mark.parametrize("path", [
    "/api/v1/broker/snapshot?symbols=2330/../orders",
    "/api/v1/engine/bots/Bot%3Flimit%3D1/history",
])
def test_a_value_that_would_change_the_upstream_url_is_refused(client, authed, path):
    """A symbol or bot id goes into an upstream path only if it has the right
    shape, so it cannot point FinHub at another route of the engine or broker."""
    res = client.get(path, headers=authed)
    assert res.status_code == 422
    assert res.json()["detail"] == "invalid symbol, order id or bot id"


def test_identifiers_with_the_right_shape_pass():
    from cjtrade.apps.FinHub.clients import _segments as seg
    assert seg.segment("00632R", seg.SYMBOL, "symbol") == "00632R"
    assert seg.segment("Bot_U1", seg.BOT_ID, "bot id") == "Bot_U1"
    with pytest.raises(seg.BadSegment):
        seg.segment("2330?x=1", seg.SYMBOL, "symbol")
