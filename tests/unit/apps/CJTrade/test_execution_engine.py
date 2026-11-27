"""ExecutionEngine places, tracks, resolves and cancels the bots' orders.

The broker is a fake account client; the risk gate is the real one.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cjtrade.apps.CJTrade import main as engine
from cjtrade.apps.CJTrade.protocol import OrderIntent
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.risk import RiskGate
from cjtrade.pkgs.risk import RiskLimits

T0 = datetime(2026, 3, 2, 9, 1)
T1 = T0 + timedelta(minutes=1)


def intent(action=OrderAction.BUY, qty=2, price=100.0, symbol="2330",
           bot="Bot_A", order_id=None, reason="signal"):
    order = Order(product=Product(symbol), action=action, price=price,
                  quantity=qty, price_type=PriceType.LMT,
                  order_type=OrderType.ROD, order_lot=OrderLot.Common,
                  created_at=T0)
    if order_id:
        order.id = order_id
    return OrderIntent(bot_id=bot, order=order, reason=reason)


def result(status, linked="", message="ok"):
    return OrderResult(status=status, message=message, metadata={},
                       linked_order=linked)


class FakeBroker:
    """An account client: places, lists and cancels, and reports one state."""

    def __init__(self, status=OrderStatus.FILLED):
        self.status = status
        self.placed, self.cancelled, self.listings = [], [], 0
        self.trades = []
        self.cancel_answer = {}
        self.state = SimpleNamespace(balance=900.0, positions=[
            Position("2330", 2, 100.0, 100.0, 200.0), Position("2317", 1, 50, 50, 50)])

    def place_order(self, order):
        if isinstance(self.status, Exception):
            raise self.status
        self.placed.append(order)
        return result(self.status, linked=order.id)

    def get_account_state(self):
        return self.state

    def list_orders(self):
        self.listings += 1
        if isinstance(self.trades, Exception):
            raise self.trades
        return self.trades

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        answer = self.cancel_answer.get(order_id, result(OrderStatus.CANCELLED))
        if isinstance(answer, Exception):
            raise answer
        return answer


def trade(order_id, status):
    return SimpleNamespace(id=order_id, status=status)


def gate(**kw):
    return RiskGate(RiskLimits(**kw), initial_equity=1e6)


def run(coro):
    return asyncio.run(coro)


class TestPaperExecution:
    def test_a_buy_fills_at_its_price_and_opens_a_position(self):
        eng = engine.ExecutionEngine(None, initial_balance=1000)
        report = run(eng.execute(intent(qty=3, price=100)))
        ev = report.event
        assert (ev.new_status, ev.filled_quantity, ev.filled_price, ev.filled_value,
                ev.message, ev.timestamp) == \
            (OrderStatus.FILLED, 3, 100, 300, "signal", T0)
        assert report.balance == 700
        assert (report.position.quantity, report.position.avg_cost,
                report.position.market_value) == (3, 100, 300)

    def test_a_second_buy_averages_the_cost_and_marks_to_the_new_price(self):
        eng = engine.ExecutionEngine(None, initial_balance=1000)
        run(eng.execute(intent(qty=2, price=100)))
        pos = run(eng.execute(intent(qty=2, price=110))).position
        assert (pos.quantity, pos.avg_cost, pos.unrealized_pnl) == (4, 105, 20)

    def test_each_bot_has_its_own_ledger(self):
        eng = engine.ExecutionEngine(None, initial_balance=1000)
        run(eng.execute(intent(qty=5, price=100, bot="Bot_A")))
        assert run(eng.execute(intent(qty=1, price=100, bot="Bot_B"))).balance == 900

    def test_a_buy_the_balance_cannot_cover_is_rejected_unfilled(self):
        eng = engine.ExecutionEngine(None, initial_balance=100)
        ev = run(eng.execute(intent(qty=2, price=100))).event
        assert (ev.new_status, ev.filled_quantity, ev.filled_price, ev.message) == \
            (OrderStatus.REJECTED, 0, None, "insufficient balance")

    def test_a_buy_of_no_shares_is_rejected_as_invalid(self):
        eng = engine.ExecutionEngine(None)
        assert run(eng.execute(intent(qty=0))).event.message == "invalid qty"

    def test_selling_what_is_not_held_is_rejected(self):
        eng = engine.ExecutionEngine(None, initial_balance=1000)
        run(eng.execute(intent(qty=1)))
        ev = run(eng.execute(intent(OrderAction.SELL, qty=2))).event
        assert (ev.new_status, ev.message) == (OrderStatus.REJECTED,
                                               "no/insufficient position")

    def test_selling_everything_returns_the_cash_and_clears_the_cost(self):
        eng = engine.ExecutionEngine(None, initial_balance=1000)
        run(eng.execute(intent(qty=2, price=100)))
        report = run(eng.execute(intent(OrderAction.SELL, qty=2, price=120)))
        assert report.balance == 1040
        assert (report.position.quantity, report.position.avg_cost,
                report.position.market_value) == (0, 0.0, 0)

    def test_an_action_that_is_neither_buy_nor_sell_is_rejected(self):
        eng = engine.ExecutionEngine(None)
        ev = run(eng.execute(intent(OrderAction.CANCEL))).event
        assert ev.new_status == OrderStatus.REJECTED
        assert ev.message.startswith("unsupported action")

    def test_a_gate_refusal_is_a_rejection_from_the_bots_point_of_view(self):
        g = gate()
        g.halt("kill switch")
        eng = engine.ExecutionEngine(None, initial_balance=1000, gate=g)
        report = run(eng.execute(intent()))
        assert (report.event.new_status, report.event.message, report.balance) == \
            (OrderStatus.REJECTED, "trading halted: kill switch", 1000)


class TestBrokerExecution:
    def test_a_filled_order_reports_the_whole_quantity_and_the_brokers_account(self):
        broker = FakeBroker(OrderStatus.FILLED)
        eng = engine.ExecutionEngine(broker)
        report = run(eng.execute(intent(qty=2)))
        assert (report.event.new_status, report.event.filled_quantity) == \
            (OrderStatus.FILLED, 2)
        assert report.balance == 900 and report.position.symbol == "2330"
        assert eng._open == {}

    def test_the_bots_order_id_is_the_one_placed(self):
        broker = FakeBroker()
        it = intent(order_id="bot-order-1")
        run(engine.ExecutionEngine(broker).execute(it))
        assert broker.placed[0].id == "bot-order-1"

    def test_a_resting_order_is_remembered_and_reported_unfilled(self):
        broker = FakeBroker(OrderStatus.COMMITTED_WAIT_MATCHING)
        eng = engine.ExecutionEngine(broker)
        it = intent(order_id="o1")
        report = run(eng.execute(it))
        assert report.event.filled_quantity == 0 and report.event.filled_price is None
        assert eng._open == {"o1": ("Bot_A", it.order)}

    def test_a_partial_fill_is_reported_as_nothing_filled_yet(self):
        report = run(engine.ExecutionEngine(FakeBroker(OrderStatus.PARTIAL))
                     .execute(intent(qty=5)))
        assert report.event.filled_quantity == 0

    def test_a_position_in_a_symbol_the_account_does_not_hold_is_none(self):
        report = run(engine.ExecutionEngine(FakeBroker()).execute(intent(symbol="0050")))
        assert report.position is None

    def test_a_broker_error_on_placement_is_a_rejection_carrying_the_error(self):
        eng = engine.ExecutionEngine(FakeBroker(ConnectionError("broker down")))
        ev = run(eng.execute(intent())).event
        assert (ev.new_status, ev.message) == (OrderStatus.REJECTED, "broker down")

    def test_a_gate_refusal_never_reaches_the_broker(self):
        broker = FakeBroker()
        eng = engine.ExecutionEngine(broker, gate=gate(max_orders_per_bar=0))
        report = run(eng.execute(intent()))
        assert broker.placed == []
        assert report.event.new_status == OrderStatus.REJECTED
        assert report.balance == 900

    def test_a_resting_buy_counts_against_the_bots_allocation(self):
        g = gate()
        eng = engine.ExecutionEngine(FakeBroker(OrderStatus.COMMITTED_WAIT_MATCHING), gate=g)
        run(eng.execute(intent(qty=2, price=100)))
        assert g.exposures == {"Bot_A": 200}

    def test_a_filled_buy_moves_into_the_bots_held_cost(self):
        g = gate()
        run(engine.ExecutionEngine(FakeBroker(OrderStatus.FILLED), gate=g)
            .execute(intent(qty=2, price=100, order_id="o1")))
        assert g.exposures == {"Bot_A": 200} and g._resting == {}

    def test_an_order_the_broker_rejected_is_not_recorded_by_the_gate(self):
        g = gate()
        run(engine.ExecutionEngine(FakeBroker(OrderStatus.REJECTED), gate=g)
            .execute(intent()))
        assert g.exposures == {}


def resting_engine(*order_ids, bot="Bot_A", g=None):
    broker = FakeBroker(OrderStatus.COMMITTED_WAIT_MATCHING)
    eng = engine.ExecutionEngine(broker, gate=g)
    for oid in order_ids:
        b, _, rest = oid.partition(":")
        run(eng.execute(intent(order_id=rest or b, bot=b if rest else bot)))
    return eng, broker


class TestPollOpenOrders:
    def test_nothing_is_asked_when_nothing_is_resting(self):
        eng, broker = resting_engine()
        assert run(eng.poll_open_orders(T1)) == [] and broker.listings == 0

    def test_the_paper_path_has_nothing_to_poll(self):
        assert run(engine.ExecutionEngine(None).poll_open_orders(T1)) == []

    def test_a_resting_order_that_filled_is_reported_at_the_bar_it_was_seen(self):
        g = gate()
        eng, broker = resting_engine("o1", g=g)
        broker.trades = [trade("o1", "FILLED")]
        [report] = run(eng.poll_open_orders(T1))
        ev = report.event
        assert (ev.order_id, ev.new_status, ev.filled_quantity, ev.timestamp,
                ev.message) == ("o1", OrderStatus.FILLED, 2, T1, "resolved on refresh")
        assert eng._open == {} and g._resting == {}

    def test_an_order_still_resting_is_left_to_the_next_poll(self):
        eng, broker = resting_engine("o1")
        broker.trades = [trade("o1", "COMMITTED_WAIT_MATCHING"), trade("x", "FILLED")]
        assert run(eng.poll_open_orders(T1)) == [] and "o1" in eng._open

    def test_a_status_string_nobody_knows_ends_the_order_as_unknown(self):
        eng, broker = resting_engine("o1")
        broker.trades = [trade("o1", "SOMETHING_NEW")]
        [report] = run(eng.poll_open_orders(T1))
        assert report.event.new_status == OrderStatus.UNKNOWN and eng._open == {}

    def test_an_order_the_broker_no_longer_lists_is_reported_unknown(self):
        eng, broker = resting_engine("o1", "o2")
        broker.trades = [trade("o1", "COMMITTED_WAIT_MATCHING")]
        [report] = run(eng.poll_open_orders(T1))
        assert (report.event.order_id, report.event.new_status) == \
            ("o2", OrderStatus.UNKNOWN)
        assert list(eng._open) == ["o1"]

    def test_an_empty_listing_is_treated_as_a_hiccup_not_as_every_order_gone(self):
        eng, broker = resting_engine("o1")
        broker.trades = []
        assert run(eng.poll_open_orders(T1)) == [] and "o1" in eng._open

    def test_a_failed_listing_reports_nothing_and_keeps_the_orders(self):
        eng, broker = resting_engine("o1")
        broker.trades = ConnectionError("down")
        assert run(eng.poll_open_orders(T1)) == [] and "o1" in eng._open


class TestCancelOpenOrders:
    def test_every_resting_order_is_cancelled_and_reported(self):
        eng, broker = resting_engine("o1", "o2")
        reports = run(eng.cancel_open_orders(T1))
        assert broker.cancelled == ["o1", "o2"] and eng._open == {}
        assert {(r.event.order_id, r.event.new_status, r.event.timestamp)
                for r in reports} == {("o1", OrderStatus.CANCELLED, T1),
                                      ("o2", OrderStatus.CANCELLED, T1)}

    def test_only_the_named_bots_orders_are_cancelled(self):
        eng, broker = resting_engine("Bot_A:a1", "Bot_B:b1")
        reports = run(eng.cancel_open_orders(T1, only_bot="Bot_B"))
        assert broker.cancelled == ["b1"] and list(eng._open) == ["a1"]
        assert [r.bot_id for r in reports] == ["Bot_B"]

    def test_the_paper_path_has_nothing_to_cancel(self):
        assert run(engine.ExecutionEngine(None).cancel_open_orders(T1)) == []

    def test_a_cancel_that_raises_leaves_the_order_tracked(self):
        eng, broker = resting_engine("o1")
        broker.cancel_answer["o1"] = ConnectionError("down")
        assert run(eng.cancel_open_orders(T1)) == [] and "o1" in eng._open

    def test_a_cancel_with_no_answer_is_reported_unknown_with_the_given_reason(self):
        eng, broker = resting_engine("o1")
        broker.cancel_answer["o1"] = None
        [report] = run(eng.cancel_open_orders(T1, reason="risk halt"))
        assert (report.event.new_status, report.event.message) == \
            (OrderStatus.UNKNOWN, "risk halt")

    def test_a_cancelled_buy_releases_its_capital(self):
        g = gate()
        eng, _ = resting_engine("o1", g=g)
        run(eng.cancel_open_orders(T1))
        assert g.exposures == {"Bot_A": 0.0}

    def test_a_refused_cancel_keeps_the_capital_reserved(self):
        g = gate()
        eng, broker = resting_engine("o1", g=g)
        broker.cancel_answer["o1"] = result(OrderStatus.REJECTED, message="already filled")
        [report] = run(eng.cancel_open_orders(T1))
        assert report.event.message == "already filled"
        assert g.exposures == {"Bot_A": 200}


class TestAsStatus:
    @pytest.mark.parametrize("raw,status", [("FILLED", OrderStatus.FILLED),
                                            ("CANCELLED", OrderStatus.CANCELLED),
                                            ("Filled", OrderStatus.UNKNOWN),
                                            ("", OrderStatus.UNKNOWN)])
    def test_a_wire_status_is_widened_to_unknown_rather_than_guessed(self, raw, status):
        assert engine._as_status(raw) is status
