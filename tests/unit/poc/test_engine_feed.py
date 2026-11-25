"""The trading engine feeds its bots closed 1m bars from MarketData.get_kbars.

Nothing here opens a socket or reaches a server: the broker, the clock and the
PUB socket are fakes.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import pytest
from cjtrade.pkgs.models.kbar import Kbar

ENGINE_DIR = Path(__file__).resolve().parents[3] / "poc" / "trading_engine"
sys.path.insert(0, str(ENGINE_DIR))

import protocol  # noqa: E402

_spec = importlib.util.spec_from_file_location("engine_main", ENGINE_DIR / "main.py")
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

T0 = datetime(2026, 3, 2, 9, 1)


def bar(symbol, minute, close=100.0):
    ts = T0 + timedelta(minutes=minute)
    return Kbar(ts, close, close + 1, close - 1, close, 5, symbol)


class FakeMarket:
    """Closed bars only, as every MarketData returns them, up to `self.now`."""

    def __init__(self, bars):
        self.bars, self.now, self.calls = bars, T0, []

    def get_kbars(self, symbol, start, end, interval="1m"):
        self.calls.append((symbol, start, end))
        return [b for b in self.bars if b.symbol == symbol
                and start <= b.timestamp < end and b.timestamp <= self.now]


class FakeClient:
    def __init__(self, bars):
        self.market = FakeMarket(bars)


class SteppingClock:
    """ReplayClock's interface without a server: `now` steps through stamps."""

    def __init__(self, stamps, market):
        self.stamps, self.i, self.market = stamps, 0, market
        market.now = stamps[0]

    @property
    def finished(self):
        return self.i >= len(self.stamps) - 1

    @property
    def now(self):
        return self.stamps[self.i]

    async def sleep(self, _seconds):
        self.i += 1
        self.market.now = self.now


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_multipart(self, parts):
        topic, payload = parts
        self.sent.append((topic.decode(), protocol.decode(payload)))


def run_hub(bars, stamps, symbols):
    client = FakeClient(bars)
    clock = SteppingClock(stamps, client.market)
    hub = engine.EventHub(account_client=client, clock=clock)
    for s in symbols:
        hub.subscribe_price_feed(s)
    sock = FakeSocket()
    hub.pub_socket = sock
    asyncio.run(hub._reload_loop())
    return hub, sock, client


def test_a_price_update_carries_a_kbar_across_the_wire():
    update = protocol.PriceUpdate(seq=3, bar=bar("2330", 0, 101.5))
    back = protocol.decode(protocol.encode(update))
    assert isinstance(back.bar, Kbar)
    assert (back.seq, back.bar.timestamp, back.bar.high, back.bar.symbol) == \
        (3, T0, 102.5, "2330")


def test_each_bar_is_published_once_with_its_own_high_and_low():
    bars = [bar("2330", m, 100 + m) for m in range(4)]
    stamps = [b.timestamp for b in bars]
    _, sock, _ = run_hub(bars, stamps, ["2330"])
    updates = [m for _, m in sock.sent if isinstance(m, protocol.PriceUpdate)]
    # The replay clock never publishes its last stamp; that is ReplayClock's
    # own rule (finished at len-1), unchanged here.
    assert [u.bar.timestamp for u in updates] == stamps[:-1]
    assert [u.seq for u in updates] == [0, 1, 2]
    assert [(u.bar.high, u.bar.low) for u in updates] == \
        [(101 + m, 99 + m) for m in range(3)]


def test_a_symbol_with_no_trade_this_minute_gets_a_feed_status_not_a_repeat():
    bars = [bar("2330", m) for m in range(4)] + [bar("2357", 0), bar("2357", 2)]
    stamps = [T0 + timedelta(minutes=m) for m in range(4)]
    _, sock, _ = run_hub(bars, stamps, ["2330", "2357"])
    quiet = [(t, m) for t, m in sock.sent if t == "2357"]
    assert [m.bar.timestamp.minute for _, m in quiet] == [1, 3]
    notes = [m.reason for t, m in sock.sent if isinstance(m, protocol.FeedStatus)]
    assert notes == ["no trade this bar: 2357"]


def test_a_bar_that_arrives_late_is_published_next_round_not_lost():
    hub = engine.EventHub(account_client=FakeClient([]), clock=None)
    market = hub.client.market
    market.bars = [bar("2330", 0)]
    market.now = T0
    assert [b.timestamp for b in hub._new_bars("2330", T0)] == [T0]
    hub._last_bar["2330"] = T0
    # 09:02 was not there at 09:02; it shows up when asked at 09:03.
    assert hub._new_bars("2330", T0 + timedelta(minutes=1)) == []
    market.bars += [bar("2330", 1), bar("2330", 2)]
    market.now = T0 + timedelta(minutes=2)
    got = hub._new_bars("2330", T0 + timedelta(minutes=2))
    assert [b.timestamp.minute for b in got] == [2, 3]


def test_the_first_round_starts_at_now_not_with_the_days_history():
    hub = engine.EventHub(account_client=FakeClient([]), clock=None)
    market = hub.client.market
    market.bars = [bar("2330", m) for m in range(5)]
    market.now = T0 + timedelta(minutes=4)
    got = hub._new_bars("2330", market.now)
    assert [b.timestamp for b in got] == [market.now]


def test_a_bot_waiting_on_a_quiet_symbol_is_not_reported_silent():
    reg = engine.BotRegistry()
    reg.expect(["Bot_A", "Bot_B"], 0)
    for bot_id in ("Bot_A",):
        reg.record(protocol.BotStatus(
            bot_id=bot_id, seq=4, bar_index=5, market_time=T0, started_at=T0,
            bars_seen=5, bars_dropped=0, inflight={}, balance=0.0, monitors={}), 0)
    # Bot_A answered seq 4 and its symbol has published nothing since. Bot_B
    # never answered at all.
    reg.excuse_caught_up({"Bot_A": 4, "Bot_B": 0}, 30)
    assert reg.newly_silent(30, 20) == ["Bot_B"]


@pytest.fixture
def server(tmp_path, monkeypatch):
    from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer
    from cjtrade.apps.ArenaX.demo_backend import ArenaX_Backend_None
    from cjtrade.pkgs.marketdata import Capabilities
    from cjtrade.pkgs.marketdata import MarketData
    from cjtrade.pkgs.marketdata.base import in_window
    from cjtrade.pkgs.marketdata.base import to_window

    class Day(MarketData):
        name = "day"

        @property
        def capabilities(self):
            return Capabilities(intervals=frozenset({"1m"}))

        def get_kbars(self, symbol, start, end, interval="1m"):
            start, end = to_window(start, end)
            return in_window([bar(symbol, m) for m in range(10)], start, end)

    monkeypatch.setattr(ArenaX_Backend_None, "_initialize_market_time", lambda self: None)
    srv = ArenaX_BrokerSideServer(backend_str="demo", market_data=Day(),
                                  price_db_path=str(tmp_path / "p.db"))
    srv.backend.market.set_historical_time_abs(real_init_time=datetime.now(),
                                               mock_init_time=T0)
    srv.backend.market.set_market_time(T0 + timedelta(minutes=2))
    srv._running = True          # what serve_forever sets once the backend is up
    return srv._app.test_client()


def test_the_timeline_shows_where_the_bars_are_before_the_clock_reaches_them(server):
    window = "start=2026-03-02&end=2026-03-03"
    kbars = server.get(f"/api/v1/market/2330/kbars?{window}T00:00:00&interval=1m").get_json()
    assert len(kbars["result"]) == 3, "09:01-09:03 only: the clock is at 09:03"
    timeline = server.get(f"/api/v1/clock/timeline?symbols=2330,2317&{window}").get_json()
    assert timeline["ok"] and len(timeline["result"]) == 10
    assert timeline["result"][0] == T0.isoformat()
