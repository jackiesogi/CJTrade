"""Master tracks its bots and moves their messages, and the hub holds or resumes the feed.

The ZMQ sockets, the broker and the clock are fakes; nothing is bound.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

from cjtrade.apps.CJTrade import main as engine
from cjtrade.apps.CJTrade import protocol
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

T0 = datetime(2026, 3, 2, 9, 1)


def status(bot_id="Bot_A", seq=0, market_time=T0, **kw):
    fields = dict(bot_id=bot_id, seq=seq, bar_index=seq + 1,
                  market_time=market_time, started_at=T0, bars_seen=seq + 1,
                  bars_dropped=0, inflight={}, balance=1234.4, monitors={})
    return protocol.BotStatus(**{**fields, **kw})


def order_intent(bot="Bot_A", qty=1):
    order = Order(product=Product("2330"), action=OrderAction.BUY, price=10.0,
                  quantity=qty, price_type=PriceType.LMT,
                  order_type=OrderType.ROD, order_lot=OrderLot.Common,
                  created_at=T0)
    return protocol.OrderIntent(bot_id=bot, order=order)


class FakePub:
    def __init__(self):
        self.sent = []

    async def send_multipart(self, parts):
        topic, payload = parts
        self.sent.append((topic.decode(), protocol.decode(payload)))


class FakePull:
    """Serves queued wire messages; raises CancelledError once drained."""

    def __init__(self, *messages):
        self.queue = [m if isinstance(m, bytes) else protocol.encode(m)
                      for m in messages]

    async def poll(self, timeout):
        await asyncio.sleep(0)
        return bool(self.queue)

    async def recv(self):
        if not self.queue:
            raise asyncio.CancelledError
        return self.queue.pop(0)


class TestBotRegistry:
    def test_a_handshake_counts_as_heard_but_is_not_history(self):
        reg = engine.BotRegistry()
        reg.record(status(seq=-1, market_time=None), 0)
        assert reg.heard_from() == {"Bot_A"} and list(reg.history) == []

    def test_history_is_bounded(self):
        reg = engine.BotRegistry(history=2)
        for seq in range(3):
            reg.record(status(seq=seq), seq)
        assert [s.seq for s in reg.history] == [1, 2]

    def test_latest_is_a_copy(self):
        reg = engine.BotRegistry()
        reg.record(status(), 0)
        reg.latest.clear()
        assert list(reg.latest) == ["Bot_A"]

    def test_a_bot_is_behind_until_it_reports_the_wanted_seq(self):
        reg = engine.BotRegistry()
        reg.record(status("Bot_A", seq=3), 0)
        assert reg.behind({"Bot_A": 4, "Bot_B": -1}) == ["Bot_A", "Bot_B"]
        assert reg.behind({"Bot_A": 3}) == []

    def test_a_stopped_bot_is_never_waited_for(self):
        reg = engine.BotRegistry()
        reg.mark_stopped("Bot_A", "operator")
        assert reg.behind({"Bot_A": 0}) == []

    def test_silence_is_reported_once_and_rearmed_by_a_report(self):
        reg = engine.BotRegistry()
        reg.expect(["Bot_A"], 0)
        assert reg.newly_silent(19, 20) == []
        assert reg.newly_silent(20, 20) == ["Bot_A"]
        assert reg.newly_silent(21, 20) == []
        reg.record(status(), 21)
        assert reg.newly_silent(41, 20) == ["Bot_A"]

    def test_expect_does_not_reset_a_bot_already_on_the_clock(self):
        reg = engine.BotRegistry()
        reg.expect(["Bot_A"], 0)
        reg.expect(["Bot_A"], 15)
        assert reg.newly_silent(20, 20) == ["Bot_A"]

    def test_a_stopped_bot_is_not_reported_silent(self):
        reg = engine.BotRegistry()
        reg.expect(["Bot_A"], 0)
        reg.mark_stopped("Bot_A", "operator")
        assert reg.newly_silent(100, 20) == []
        assert (reg.is_stopped("Bot_A"), reg.stop_reason("Bot_A"),
                reg.stop_reason("Bot_B"), reg.stopped) == \
            (True, "operator", None, {"Bot_A": "operator"})

    def test_a_bot_nothing_was_heard_from_says_so(self):
        assert engine.BotRegistry().summary_line("Bot_A") == "Bot_A: nothing heard yet"

    def test_the_summary_line_shows_known_monitors_inflight_and_why(self):
        reg = engine.BotRegistry()
        reg.record(status(seq=4, bars_dropped=1, inflight={"2330": "ab12"},
                          monitors={"regime": "trend", "other": 1,
                                    "last_decision": "ADX above 25"}), 0)
        assert reg.summary_line("Bot_A") == (
            "Bot_A: bar 5 dropped=1 balance=1234 inflight[2330:ab12]  regime=trend"
            f"\n{' ' * 10}why: ADX above 25")

    def test_the_summary_line_of_a_quiet_bot_is_just_its_counters(self):
        reg = engine.BotRegistry()
        reg.record(status(monitors=None, inflight=None), 0)
        assert reg.summary_line("Bot_A") == "Bot_A: bar 1 dropped=0 balance=1234"


class TestWaitFor:
    def test_an_already_true_condition_returns_at_once(self):
        reg = engine.BotRegistry()
        assert asyncio.run(reg.wait_for(lambda: True, 0)) is True

    def test_a_report_arriving_while_waiting_wakes_the_wait(self):
        reg = engine.BotRegistry()

        async def scenario():
            async def report():
                await asyncio.sleep(0.01)
                reg.record(status(seq=2), 0)
            task = asyncio.create_task(report())
            ok = await reg.wait_for(lambda: not reg.behind({"Bot_A": 2}), 5)
            await task
            return ok
        assert asyncio.run(scenario()) is True

    def test_a_condition_that_never_comes_true_times_out(self):
        reg = engine.BotRegistry()
        assert asyncio.run(reg.wait_for(lambda: False, 0.02)) is False


class TestAwaitBots:
    def test_bots_that_answer_the_sync_are_recorded_and_the_rest_returned(self):
        reg = engine.BotRegistry()
        pub = FakePub()
        pull = FakePull(status("Bot_A", seq=-1, market_time=None),
                        protocol.FeedStatus(market_open=True, reason="x",
                                            bars_served=0, sent_at=T0))
        missing = asyncio.run(engine.await_bots(pub, pull, reg,
                                                ["Bot_C", "Bot_A", "Bot_B"], 0.05))
        assert missing == ["Bot_B", "Bot_C"]
        assert reg.heard_from() == {"Bot_A"}
        topic, msg = pub.sent[0]
        assert (topic, msg.reason) == (protocol.FEED_STATUS_TOPIC,
                                       protocol.FEED_SYNC_REASON)

    def test_every_bot_answering_ends_the_wait(self):
        pull = FakePull(status("Bot_A", seq=-1, market_time=None))
        assert asyncio.run(engine.await_bots(FakePub(), pull, engine.BotRegistry(),
                                             ["Bot_A"], 5)) == []


class TestHandleBotMessages:
    def test_status_is_recorded_intents_are_executed_and_junk_is_survived(self):
        reg = engine.BotRegistry()
        pub = FakePub()
        hub = SimpleNamespace(bars=7, market_time=T0)
        pull = FakePull(status("Bot_A", seq=0), b"\x00not msgpack",
                        protocol.FeedStatus(market_open=True, reason="x",
                                            bars_served=0, sent_at=T0),
                        order_intent())
        eng = engine.ExecutionEngine(None, initial_balance=100)
        try:
            asyncio.run(engine.handle_bot_messages(pull, pub, eng, reg, hub))
        except asyncio.CancelledError:
            pass
        assert reg._heard_at_bar == {"Bot_A": 7}
        [(topic, report)] = pub.sent
        assert topic == "Bot_A" and report.event.new_status == OrderStatus.FILLED


class TestPublishReport:
    def test_a_report_goes_out_on_its_bots_topic(self):
        pub = FakePub()
        report = asyncio.run(engine.ExecutionEngine(None).execute(order_intent("Bot_Z")))
        asyncio.run(engine.publish_report(pub, report))
        [(topic, back)] = pub.sent
        assert topic == "Bot_Z" and back.event.order_id == report.event.order_id


class StampClock:
    """Steps through fixed stamps; no `now` when `with_now` is False."""

    def __init__(self, n, with_now=True):
        self.n, self.i, self.with_now = n, 0, with_now

    @property
    def finished(self):
        return self.i >= self.n

    def __getattr__(self, name):
        if name == "now" and self.with_now:
            return T0 + timedelta(minutes=self.i)
        raise AttributeError(name)

    async def sleep(self, _seconds):
        self.i += 1


class FakeMarket:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def get_kbars(self, symbol, start, end, interval="1m"):
        if symbol in self.fail:
            raise ConnectionError("kbars down")
        # The bar that closed at `now`: the hub asks up to now + one bar.
        return [Kbar(end - timedelta(minutes=1), 10, 11, 9, 10, 1, symbol)]


class FakeClient:
    def __init__(self, fail=(), market_time=None):
        self.market = FakeMarket(fail)
        self.market_time = market_time

    def get_market_time(self):
        if isinstance(self.market_time, Exception):
            raise self.market_time
        return {"mock_current_time": self.market_time}


def feed_notes(pub):
    return [(m.market_open, m.reason) for t, m in pub.sent
            if isinstance(m, protocol.FeedStatus)]


class TestEventHubSession:
    def test_without_a_session_check_the_market_is_always_open(self):
        hub = engine.EventHub(None, None)
        assert asyncio.run(hub._market_is_open()) is True

    def test_a_session_check_that_fails_is_treated_as_open(self):
        def broken():
            raise ConnectionError("down")
        hub = engine.EventHub(None, None, session_check=broken)
        assert asyncio.run(hub._market_is_open()) is True

    def test_a_closed_market_holds_the_feed_and_says_so_then_resumes(self):
        answers = iter([False, False, True])
        hub = engine.EventHub(FakeClient(), StampClock(3),
                              session_check=lambda: next(answers))
        hub.subscribe_price_feed("2330")
        pub = FakePub()
        hub.pub_socket = pub
        asyncio.run(hub._reload_loop())
        assert feed_notes(pub) == [(False, "market closed"), (False, "market closed"),
                                   (True, "market open")]
        assert hub.bars == 1 and hub.seq_of("2330") == 0

    def test_feed_status_with_no_socket_yet_is_dropped(self):
        asyncio.run(engine.EventHub(None, None)._publish_feed_status(True, "x"))


class TestEventHubRound:
    def test_a_round_whose_market_time_cannot_be_read_is_skipped(self):
        hub = engine.EventHub(FakeClient(market_time=ConnectionError("down")),
                              StampClock(2, with_now=False))
        hub.subscribe_price_feed("2330")
        hub.pub_socket = FakePub()
        asyncio.run(hub._reload_loop())
        assert hub.bars == 0 and hub.pub_socket.sent == []

    def test_the_brokers_market_time_is_used_when_the_clock_has_none(self):
        hub = engine.EventHub(FakeClient(market_time=T0), StampClock(0, with_now=False))
        assert hub._market_now() == T0

    def test_with_no_broker_and_no_clock_time_the_wall_clock_is_used(self):
        before = datetime.now()
        assert engine.EventHub(None, None)._market_now() >= before

    def test_a_symbol_whose_bars_fail_is_skipped_and_the_rest_published(self):
        got = []

        async def after(seqs):
            got.append(("after", seqs))

        async def end(ts):
            got.append(("end", ts))
        hub = engine.EventHub(FakeClient(fail={"2317"}), StampClock(1),
                              on_bar_end=end, after_publish=after)
        for s in ("2330", "2317"):
            hub.subscribe_price_feed(s)
        hub.pub_socket = FakePub()
        asyncio.run(hub._reload_loop())
        assert [t for t, _ in hub.pub_socket.sent] == ["2330"]
        assert got == [("after", {"2330": 0}), ("end", T0)]
        assert (hub.seq_of("2330"), hub.seq_of("2317")) == (0, -1)

    def test_without_a_broker_the_hub_publishes_a_made_up_bar(self, monkeypatch):
        monkeypatch.setattr(engine.random, "gauss", lambda mu, sigma: 500.0)
        hub = engine.EventHub(None, None)
        [b] = hub._new_bars("2330", T0.replace(second=42))
        # Clamped to the 50..200 band, stamped on the minute.
        assert (b.timestamp, b.open, b.close, b.high, b.low) == \
            (T0, 100.0, 200.0, 200.0, 100.0)

    def test_start_runs_the_loop_on_the_given_socket(self):
        async def scenario():
            hub = engine.EventHub(FakeClient(), StampClock(1))
            hub.subscribe_price_feed("2330")
            pub = FakePub()
            await hub.start(pub)
            return hub, pub
        hub, pub = asyncio.run(scenario())
        assert hub.pub_socket is pub and hub.bars == 1
