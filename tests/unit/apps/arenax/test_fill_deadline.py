"""An order must not fill on a bar later than its time-in-force deadline.

The clock is free to jump over the close: a replay driver steps from the last
bar of one session (13:24, say) straight to the first bar of the next, so
nothing is ever asked about a resting order while the clock sits past 13:30.
Before the clamp, that let a ROD order placed at 13:20 match the *next day's*
opening bars -- reproduced against a live server as a 09:01 fill 19 hours after
its own expiry.
"""
from datetime import datetime
from datetime import timedelta

import pandas as pd
import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_AccountState
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.time_in_force import policy_for
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs.models.cost import CostModel
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

D1 = datetime(2025, 9, 1)           # Monday
D2 = datetime(2025, 9, 2)           # Tuesday


class _StubMarket:
    """Only what the matcher reads: historical_data, a clock, a calendar."""

    def __init__(self, bars):
        index = pd.DatetimeIndex([ts for ts, _ in bars])
        self.historical_data = {
            "2317": {
                "data": pd.DataFrame({"Close": [c for _, c in bars]}, index=index),
                "timestamps": index.to_numpy(),
            }
        }
        self.start_date = index[0].to_pydatetime()
        self.calendar = TradingCalendar()
        self.now = self.start_date

    def get_market_time(self):
        return {"mock_current_time": self.now, "mock_init_time": self.start_date}

    def is_market_open(self):
        return self.calendar.is_open(OrderLot.Common, self.now)


def _session(day, closes, start_minute=0):
    base = day.replace(hour=9, minute=0) + timedelta(minutes=start_minute)
    return [(base + timedelta(minutes=i), c) for i, c in enumerate(closes)]


def _backend(bars) -> ArenaX_BackendBase:
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
    b.account_state = ArenaX_AccountState()
    b.account_state.balance = 1_000_000.0
    b._cost_model = CostModel()
    b.market = _StubMarket(bars)
    return b


def _rest(backend, *, lot=OrderLot.Common, order_type=OrderType.ROD,
          price=100.0, placed_at=None, oid="o1") -> Order:
    """Put an order on the books the way place_order would, without its checks."""
    placed_at = placed_at or D1.replace(hour=13, minute=20)
    o = Order(
        product=Product(symbol="2317"), action=OrderAction.BUY,
        price=price, quantity=10, price_type=PriceType.LMT,
        order_type=order_type, order_lot=lot, created_at=placed_at,
        opt_field={"last_check_for_fill": placed_at}, id=oid,
    )
    backend.account_state.orders_committed.append(o)
    backend.account_state.all_order_status[o.id] = OrderStatus.COMMITTED_WAIT_MATCHING
    return o


def _status(backend, o):
    return backend.account_state.all_order_status[o.id]


# ── expires_at, the deadline the clamp uses ──────────────────────────────────

class TestExpiresAt:
    def _order(self, lot=OrderLot.Common, order_type=OrderType.ROD):
        return Order(
            product=Product(symbol="2317"), action=OrderAction.BUY,
            price=100.0, quantity=10, price_type=PriceType.LMT,
            order_type=order_type, order_lot=lot,
            created_at=D1.replace(hour=10),
        )

    def test_rod_regular_lot_expires_at_the_regular_close(self):
        got = policy_for(OrderType.ROD).expires_at(self._order(), TradingCalendar())
        assert got == D1.replace(hour=13, minute=30)

    def test_rod_odd_lot_expires_at_the_after_hours_odd_close(self):
        got = policy_for(OrderType.ROD).expires_at(
            self._order(lot=OrderLot.IntraDayOdd), TradingCalendar())
        assert got == D1.replace(hour=14, minute=30)

    def test_gtc_has_no_deadline(self):
        assert policy_for(OrderType.GTC).expires_at(
            self._order(order_type=OrderType.GTC), TradingCalendar()) is None

    @pytest.mark.parametrize("ot", [OrderType.IOC, OrderType.FOK])
    def test_immediate_policies_have_no_deadline(self, ot):
        """They get exactly one pass and are cancelled by on_no_fill, so there
        is no timestamp to clamp to."""
        assert policy_for(ot).expires_at(self._order(order_type=ot),
                                         TradingCalendar()) is None


# ── the clamp ────────────────────────────────────────────────────────────────

class TestFillWindowClamp:
    def test_rod_does_not_fill_on_the_next_day(self):
        """The regression. Day 1 never reaches the limit; day 2's open does."""
        bars = _session(D1, [105.0] * 265) + _session(D2, [95.0] * 265)
        b = _backend(bars)
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)   # the overnight jump
        b._check_if_any_order_filled()

        assert _status(b, o) == OrderStatus.COMMITTED_WAIT_MATCHING
        assert b.account_state.fill_history == []

    def test_odd_lot_rod_also_stops_at_its_own_deadline(self):
        bars = _session(D1, [105.0] * 265) + _session(D2, [95.0] * 265)
        b = _backend(bars)
        o = _rest(b, lot=OrderLot.IntraDayOdd, price=100.0,
                  placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)
        b._check_if_any_order_filled()

        assert _status(b, o) == OrderStatus.COMMITTED_WAIT_MATCHING

    def test_a_legitimate_fill_before_the_deadline_is_still_found(self):
        """The clamp must not eat fills from the unchecked tail of day 1.

        Expiring before matching would lose this one: 13:25-13:30 is inside the
        window the clock jumped over, and the order was still alive there.
        """
        day1 = _session(D1, [105.0] * 265)                      # 09:00-13:24
        day1 += _session(D1, [95.0] * 6, start_minute=265)      # 13:25-13:30
        b = _backend(day1 + _session(D2, [90.0] * 265))
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)
        b._check_if_any_order_filled()

        assert _status(b, o) == OrderStatus.FILLED
        fill = b.account_state.fill_history[0]
        assert fill["time"].startswith("2025-09-01T13:2")

    def test_gtc_still_fills_across_the_gap(self):
        """GTC has no deadline, so the clamp must not touch it."""
        bars = _session(D1, [105.0] * 265) + _session(D2, [95.0] * 265)
        b = _backend(bars)
        o = _rest(b, order_type=OrderType.GTC, price=100.0,
                  placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)
        b._check_if_any_order_filled()

        assert _status(b, o) == OrderStatus.FILLED
        assert b.account_state.fill_history[0]["time"].startswith("2025-09-02T")

    def test_fill_inside_the_session_is_unaffected(self):
        bars = _session(D1, [105.0] * 60 + [95.0] * 205)
        b = _backend(bars)
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=9, minute=0))

        b.market.now = D1.replace(hour=11)
        b._check_if_any_order_filled()

        assert _status(b, o) == OrderStatus.FILLED


# ── the sweep on the per-bar path ────────────────────────────────────────────

class TestListTradesExpires:
    def test_list_trades_expires_a_stale_rod(self):
        """The engine polls resting orders through this path every bar. It used
        to run the matcher with no time-in-force behind it, so the only thing
        that expired an order was the server's wall-clock loop."""
        bars = _session(D1, [105.0] * 265) + _session(D2, [105.0] * 265)
        b = _backend(bars)
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)
        b.list_trades()

        assert _status(b, o) == OrderStatus.CANCELLED

    def test_list_trades_leaves_a_live_order_alone(self):
        bars = _session(D1, [105.0] * 265)
        b = _backend(bars)
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=9, minute=0))

        b.market.now = D1.replace(hour=11)
        b.list_trades()

        assert _status(b, o) == OrderStatus.COMMITTED_WAIT_MATCHING

    def test_list_trades_reports_the_fill_rather_than_cancelling_it(self):
        """Fill check runs first, so an order that filled before its deadline
        is reported FILLED, not swept."""
        day1 = _session(D1, [105.0] * 265)
        day1 += _session(D1, [95.0] * 6, start_minute=265)
        b = _backend(day1 + _session(D2, [90.0] * 265))
        o = _rest(b, price=100.0, placed_at=D1.replace(hour=13, minute=20))

        b.market.now = D2.replace(hour=9, minute=1)
        trades = b.list_trades()

        assert _status(b, o) == OrderStatus.FILLED
        assert next(t for t in trades if t.id == o.id).status == OrderStatus.FILLED.value
