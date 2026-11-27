"""main() wires the broker, the bots and the replay together, and tears them down.

Everything main() reaches outward through is a fake: the form, the ZMQ
context, the account client, the bot subprocesses, the status API listener and
the report writer. No socket is bound and no process is started; the "bots"
are a few lines in FakeWire that answer the feed the way bot_runner does.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
import zmq
from cjtrade.apps.CJTrade import main as engine
from cjtrade.apps.CJTrade import protocol
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

T0 = datetime(2026, 3, 2, 9, 1)


def stamps(n):
    return [T0 + timedelta(minutes=m) for m in range(n)]


class FakeWire:
    """Both ZMQ sockets, with simulated bots on the other end.

    A bot in `handshakes` answers the startup sync once; a bot in `answers`
    reports every bar on its symbol; `orders` maps a bot to the seq on which it
    sends one buy. A BotCommand stops a bot answering.
    """

    def __init__(self, bots, answers=None, handshakes=None, orders=None):
        self.bots = dict(bots)
        self.answers = set(self.bots if answers is None else answers)
        self.handshakes = set(self.bots if handshakes is None else handshakes)
        self.orders = dict(orders or {})
        self.sent, self.bound, self.hooks = [], [], []
        self._queue = None
        self._shaken = set()

    @property
    def queue(self):
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    # -- the PUB side ------------------------------------------------------
    async def send_multipart(self, parts):
        topic, msg = parts[0].decode(), protocol.decode(parts[1])
        self.sent.append((topic, msg))
        if isinstance(msg, protocol.FeedStatus) and msg.reason == protocol.FEED_SYNC_REASON:
            for bot in sorted(self.handshakes - self._shaken):
                self._shaken.add(bot)
                self._push(status(bot, -1, None))
        elif isinstance(msg, protocol.BotCommand):
            self.answers.discard(msg.bot_id)
        elif isinstance(msg, protocol.PriceUpdate):
            for hook in self.hooks:
                hook(msg)
            for bot, sym in sorted(self.bots.items()):
                if sym != topic or bot not in self.answers:
                    continue
                if self.orders.get(bot) == msg.seq:
                    self._push(protocol.OrderIntent(bot_id=bot, order=buy(sym)))
                self._push(status(bot, msg.seq, msg.bar.timestamp))

    def _push(self, msg):
        self.queue.put_nowait(protocol.encode(msg))

    # -- the PULL side -----------------------------------------------------
    async def poll(self, timeout):
        await asyncio.sleep(0.001)
        return not self.queue.empty()

    async def recv(self):
        return await self.queue.get()

    # -- what main() does to a socket --------------------------------------
    def bind(self, address):
        self.bound.append(address)

    def of(self, kind):
        return [m for _, m in self.sent if isinstance(m, kind)]


def status(bot_id, seq, market_time):
    return protocol.BotStatus(bot_id=bot_id, seq=seq, bar_index=seq + 1,
                              market_time=market_time, started_at=T0,
                              bars_seen=seq + 1, bars_dropped=0, inflight={},
                              balance=1000.0, monitors={})


def buy(symbol, qty=1, price=10.0):
    return Order(product=Product(symbol), action=OrderAction.BUY, price=price,
                 quantity=qty, price_type=PriceType.LMT, order_type=OrderType.ROD,
                 order_lot=OrderLot.Common, created_at=T0)


class FakeContext:
    def __init__(self, wire):
        self.wire, self.kinds = wire, []

    def socket(self, kind):
        self.kinds.append(kind)
        return self.wire


class FakeAccount:
    """The ArenaX account client: one account, resting orders, a fill history."""

    def __init__(self, balance=1000.0, connect=True, fill_on_poll=True,
                 states=None, fills=None):
        self.balance, self.connect_ok, self.fill_on_poll = balance, connect, fill_on_poll
        # One entry per get_account_state call: a balance, or an exception.
        self.states = list(states or [])
        self.fills = [] if fills is None else fills
        self.placed, self.cancelled, self.disconnected = [], [], 0
        self.control_plane = SimpleNamespace(
            get_backtest_state=lambda session_id: {"fill_history": self.fills})
        self.market = SimpleNamespace(get_kbars=self._kbars)
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def connect(self):
        return self.connect_ok

    def disconnect(self):
        self.disconnected += 1

    def get_balance(self):
        return self.balance

    def get_account_state(self):
        value = self.states.pop(0) if self.states else self.balance
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(balance=value, positions=[])

    def is_market_open(self):
        return True

    def _kbars(self, symbol, start, end, interval="1m"):
        return [Kbar(end - timedelta(minutes=1), 10, 11, 9, 10, 1, symbol)]

    def place_order(self, order):
        self.placed.append(order)
        return OrderResult(status=OrderStatus.COMMITTED_WAIT_MATCHING, message="",
                           metadata={}, linked_order=order.id)

    def list_orders(self):
        status = "FILLED" if self.fill_on_poll else "COMMITTED_WAIT_MATCHING"
        return [SimpleNamespace(id=o.id, status=status) for o in self.placed]

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return OrderResult(status=OrderStatus.CANCELLED, message="", metadata={},
                           linked_order=order_id)


class FakeProc:
    def __init__(self, argv):
        self.argv, self.terminated = argv, 0

    async def wait(self):
        return 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        pass


class FakeMiddleware:
    def set_market_time(self, ts):
        pass


class Run:
    """One main() under fakes, and what it left behind."""

    def __init__(self, monkeypatch, tmp_path, *, symbols=("2330",), broker="arenax",
                 mode="backtest", fund=1000.0, roster=None, wire=None,
                 account=None, bars=3, clock=None, argv=("cjtrade",)):
        self.cfg = engine.EngineConfig(
            broker=broker, backend_mode=mode, symbols=list(symbols),
            initial_balance=fund, duration_days=1, playback_speed=0,
            start_date="2026-03-02")
        self.roster = roster if roster is not None else [
            ("Bot_A", "bot_b.py", "2330", ()), ("Bot_B", "bot_c.py", "2330", ("x",))]
        self.wire = wire or FakeWire({b: s for b, _, s, _ in self.roster})
        self.account = account or FakeAccount()
        self.ctx = FakeContext(self.wire)
        self.procs, self.views, self.reports, self.clocks = [], [], [], []
        self.runner = SimpleNamespace(cleaned=0)

        async def cleanup():
            self.runner.cleaned += 1
        self.runner.cleanup = cleanup

        async def spawn(*argv):
            proc = FakeProc(argv)
            self.procs.append(proc)
            return proc

        async def start_status(view, port):
            self.views.append((view, port))
            return self.runner

        def build_clock(client, name, cfg):
            self.clocks.append(name)
            if isinstance(clock, Exception):
                raise clock
            return clock or engine.ReplayClock(FakeMiddleware(), stamps(bars))

        monkeypatch.setenv("CJTRADE_HOME", str(tmp_path))
        monkeypatch.setattr(engine.sys, "argv", list(argv))
        monkeypatch.setattr(engine, "setup_logging", lambda level: None)
        monkeypatch.setattr(engine, "load_config", lambda: self.cfg)
        monkeypatch.setattr(engine, "ctx", self.ctx)
        monkeypatch.setattr(engine, "AccountClient", self.account)
        monkeypatch.setattr(engine, "build_clock", build_clock)
        monkeypatch.setattr(engine, "BOT_ROSTER", self.roster)
        monkeypatch.setattr(engine, "print_run_report", self.reports.append)
        monkeypatch.setattr(engine.status_api, "start", start_status)
        monkeypatch.setattr(engine.asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(engine, "BOT_HANDSHAKE_TIMEOUT_S", 0.05)
        monkeypatch.setattr(engine, "BAR_BARRIER_TIMEOUT_S", 0.05)

    def __call__(self):
        asyncio.run(engine.main())
        return self

    @property
    def view(self):
        return self.views[0][0]


@pytest.fixture
def run(monkeypatch, tmp_path):
    return lambda **kw: Run(monkeypatch, tmp_path, **kw)


class TestEarlyExits:
    def test_no_symbols_stops_before_anything_is_bound(self, run):
        r = run(symbols=())()
        assert r.ctx.kinds == [] and r.account.kwargs is None

    def test_a_broker_other_than_arenax_is_refused(self, run):
        r = run(broker="sinopac")()
        assert r.account.kwargs is None and r.procs == []

    def test_a_failed_broker_connection_aborts_before_the_clock(self, run):
        r = run(account=FakeAccount(connect=False))()
        assert r.clocks == [] and r.procs == []

    def test_a_clock_that_cannot_be_built_disconnects_and_aborts(self, run):
        r = run(clock=RuntimeError("no timeline"))()
        assert r.account.disconnected == 1 and r.procs == []

    def test_an_unreadable_roster_aborts_rather_than_running_the_default(self, run, tmp_path):
        r = run(argv=("cjtrade", f"--roster={tmp_path / 'missing.json'}"))()
        assert r.account.disconnected == 1 and r.procs == []

    def test_a_roster_with_no_bot_on_the_watch_list_starts_nothing(self, run):
        r = run(roster=[("Bot_A", "bot_b.py", "0050", ())])()
        assert r.procs == [] and r.account.disconnected == 1


class TestReplayRun:
    def test_the_engine_binds_the_feed_and_intent_sockets_and_connects_arenax(self, run, monkeypatch):
        monkeypatch.delenv("ARENAX_PORT", raising=False)
        r = run()()
        assert r.ctx.kinds == [zmq.PUB, zmq.PULL]
        assert r.wire.bound == [protocol.price_feed_address(),
                                protocol.order_intent_address()]
        assert r.account.kwargs["arenax_port"] == 8802

    def test_each_bot_is_spawned_as_a_module_with_its_session_and_symbol(self, run):
        r = run(account=FakeAccount(balance=900.0))()
        session = r.view.session_id
        assert [p.argv[1:] for p in r.procs] == [
            ("-u", "-m", "cjtrade.apps.CJTrade.bot_b", "Bot_A", "900.0", session, "2330"),
            ("-u", "-m", "cjtrade.apps.CJTrade.bot_c", "Bot_B", "900.0", session,
             "2330", "x")]

    def test_a_bot_on_a_symbol_nobody_publishes_is_not_spawned(self, run):
        r = run(roster=[("Bot_A", "bot_b.py", "2330", ()),
                        ("Bot_X", "bot_b.py", "0050", ())])()
        assert r.view.bots == ["Bot_A"]

    def test_a_roster_file_replaces_the_built_in_roster(self, run, tmp_path):
        path = tmp_path / "r.json"
        path.write_text('[{"bot_id": "U1", "script": "bot_custom.py", '
                        '"symbol": "2330", "extra": ["s.py"]}]')
        wire = FakeWire({"U1": "2330"})
        r = run(argv=("cjtrade", f"--roster={path}"), wire=wire)()
        assert r.view.bots == ["U1"] and r.procs[0].argv[-1] == "s.py"

    def test_every_bar_but_the_last_is_published_and_answered(self, run):
        r = run(bars=4)()
        updates = r.wire.of(protocol.PriceUpdate)
        assert [u.seq for u in updates] == [0, 1, 2]
        assert r.view.hub.bars == 3
        assert r.view.registry.behind({"Bot_A": 2, "Bot_B": 2}) == []

    def test_the_status_api_sees_the_run_and_is_closed_first_at_shutdown(self, run):
        r = run()()
        view, port = r.views[0]
        assert port == engine.STATUS_PORT
        assert (view.clock_name, view.bots, view.cfg) == \
            ("replay", ["Bot_A", "Bot_B"], r.cfg)
        assert r.runner.cleaned == 1

    def test_the_risk_gate_splits_the_brokers_balance_between_the_bots(self, run):
        r = run(account=FakeAccount(balance=900.0), fund=1000.0)()
        assert r.view.gate.limits.max_notional_per_bot == 450.0
        assert r.view.recorder.initial_balance == 900.0

    def test_a_resting_order_is_reported_placed_then_filled_at_bar_end(self, run):
        wire = FakeWire({"Bot_A": "2330"}, orders={"Bot_A": 0})
        r = run(roster=[("Bot_A", "bot_b.py", "2330", ())], wire=wire)()
        reports = [(t, m.event.new_status) for t, m in r.wire.sent
                   if isinstance(m, protocol.OrderReport)]
        assert reports == [("Bot_A", OrderStatus.COMMITTED_WAIT_MATCHING),
                           ("Bot_A", OrderStatus.FILLED)]
        assert r.account.cancelled == []

    def test_an_order_still_resting_at_shutdown_is_cancelled(self, run):
        wire = FakeWire({"Bot_A": "2330"}, orders={"Bot_A": 0})
        r = run(roster=[("Bot_A", "bot_b.py", "2330", ())], wire=wire,
                account=FakeAccount(fill_on_poll=False))()
        assert r.account.cancelled == [r.account.placed[0].id]
        last = r.wire.of(protocol.OrderReport)[-1].event
        assert (last.new_status, last.message) == \
            (OrderStatus.CANCELLED, "cancelled at shutdown")

    def test_equity_is_sampled_every_bar_and_the_report_written(self, run, tmp_path):
        fills = [{"time": "t", "symbol": "2330", "action": "BUY", "quantity": 1,
                  "price": 10.0}]
        r = run(bars=4, account=FakeAccount(states=[1000, 990, 980], fills=fills))()
        assert [s["value"] for s in r.view.recorder.equity_curve] == [1000, 990, 980]
        [result] = r.reports
        assert (result.session_id, result.fill_history, result.final_balance) == \
            (r.view.session_id, fills, 1000.0)
        journal = engine.paths.reports_dir() / f"engine_{r.view.session_id[:8]}.equity.jsonl"
        assert len(engine.RunRecorder.read_journal(journal)) == 3

    def test_every_bot_is_terminated_and_the_broker_disconnected_at_the_end(self, run):
        r = run()()
        assert [p.terminated for p in r.procs] == [1, 1]
        assert r.account.disconnected == 1

    def test_a_report_that_cannot_be_built_still_disconnects(self, run):
        account = FakeAccount()
        account.control_plane = SimpleNamespace(
            get_backtest_state=lambda session_id: (_ for _ in ()).throw(
                ConnectionError("server gone")))
        r = run(account=account)()
        assert r.reports == [] and account.disconnected == 1


class TestKillSwitch:
    def test_an_equity_drop_past_the_loss_limit_halts_and_pulls_resting_orders(self, run):
        wire = FakeWire({"Bot_A": "2330"}, orders={"Bot_A": 0})
        account = FakeAccount(fill_on_poll=False, states=[1000, 1000, 100])
        r = run(roster=[("Bot_A", "bot_b.py", "2330", ())], wire=wire,
                account=account, bars=3)()
        assert r.view.gate.halted and "loss limit" in r.view.gate.halt_reason
        reasons = [m.event.message for m in r.wire.of(protocol.OrderReport)]
        assert reasons[-1] == "risk halt"
        assert r.view.recorder.equity_curve[-1]["value"] == 100

    def test_an_account_unreadable_for_five_bars_halts_trading(self, run):
        down = [ConnectionError("down")] * engine.ACCOUNT_READ_MAX_FAILURES
        r = run(bars=engine.ACCOUNT_READ_MAX_FAILURES + 1,
                account=FakeAccount(states=down))()
        assert r.view.gate.halted
        assert "unreadable for 5 bars" in r.view.gate.halt_reason

    def test_an_account_read_that_recovers_does_not_halt(self, run):
        r = run(bars=4, account=FakeAccount(states=[ConnectionError("blip"), 1000, 1000]))()
        assert not r.view.gate.halted
        assert len(r.view.recorder.equity_curve) == 2


class TestQuietBots:
    def test_a_bot_that_never_answers_the_handshake_does_not_stop_the_run(self, run):
        wire = FakeWire({"Bot_A": "2330", "Bot_B": "2330"}, handshakes={"Bot_A"},
                        answers={"Bot_A"})
        r = run(wire=wire)()
        assert r.view.hub.bars == 2 and r.view.registry.heard_from() == {"Bot_A"}

    def test_a_bot_that_stops_answering_bars_is_given_up_on_and_called_silent(self, run, monkeypatch):
        monkeypatch.setattr(engine, "BOT_SILENT_BARS", 1)
        monkeypatch.setattr(engine, "BOT_STATUS_EVERY", 1)
        wire = FakeWire({"Bot_A": "2330", "Bot_B": "2330"}, answers={"Bot_A"})
        r = run(wire=wire, bars=4)()
        assert r.view.hub.bars == 3
        assert r.view.registry.behind({"Bot_B": 0}) == ["Bot_B"]
        assert "Bot_B" in r.view.registry._reported_silent


class TestStopBot:
    def test_a_bot_stopped_mid_run_is_told_and_the_rest_carry_on(self, run):
        wire = FakeWire({"Bot_A": "2330", "Bot_B": "2330"}, orders={"Bot_B": 0})
        r = run(wire=wire, bars=4, account=FakeAccount(fill_on_poll=False))
        results = []

        def stop_after_first_bar(update):
            if update.seq == 1:
                stop = r.view.stop_bot
                results.append(asyncio.ensure_future(stop("Bot_B", "bad fills")))
                results.append(asyncio.ensure_future(stop("Bot_B", "again")))
                results.append(asyncio.ensure_future(stop("Bot_Z", "typo")))
        wire.hooks.append(stop_after_first_bar)
        r()
        first, second, unknown = [f.result() for f in results]
        assert (first["ok"], first["reason"], first["position_flattened"]) == \
            (True, "bad fills", False)
        assert first["orders_cancelled"] == [r.account.placed[0].id]
        assert second == {"ok": True, "bot_id": "Bot_B", "already_stopped": True,
                          "reason": "bad fills"}
        assert unknown["ok"] is False and unknown["bots"] == ["Bot_A", "Bot_B"]
        [cmd] = wire.of(protocol.BotCommand)
        assert (cmd.bot_id, cmd.action, cmd.reason) == ("Bot_B", protocol.BOT_STOP,
                                                        "bad fills")
        assert r.view.registry.stopped == {"Bot_B": "bad fills"}
        assert r.view.hub.bars == 3


class TestLivePath:
    def test_a_live_run_uses_the_realtime_clock_and_asks_if_the_market_is_open(self, run):
        class TwoBars:
            def __init__(self):
                self.left = 2

            @property
            def finished(self):
                return self.left == 0

            async def sleep(self, _s):
                self.left -= 1
        account = FakeAccount()
        asked = []
        account.is_market_open = lambda: asked.append(1) or True
        account.get_market_time = lambda: {"mock_current_time": T0}
        r = run(mode="paper", clock=TwoBars(), account=account)()
        assert r.clocks == ["realtime"] and len(asked) == 2
        assert r.view.hub.bars == 2
