"""Unit tests for time-in-force policies."""
from datetime import datetime

import pytest
from cjtrade.apps.ArenaX.time_in_force import policy_for
from cjtrade.apps.ArenaX.time_in_force import TIFContext
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

MON = datetime(2025, 9, 1)          # a Monday


def _order(order_type=OrderType.ROD, lot=OrderLot.Common, placed_at=None) -> Order:
    return Order(
        product=Product(symbol="2317"), action=OrderAction.BUY,
        price=240.0, quantity=20, price_type=PriceType.LMT,
        order_type=order_type, order_lot=lot,
        created_at=placed_at or MON.replace(hour=10),
    )


def _ctx(h: int, m: int = 0, day=MON) -> TIFContext:
    return TIFContext(now=day.replace(hour=h, minute=m), calendar=TradingCalendar())


# ── ROD ───────────────────────────────────────────────────────────────────────

class TestROD:
    def test_rests_during_the_session(self):
        assert policy_for(OrderType.ROD).on_no_fill(_order(), _ctx(11)).cancel is False

    def test_rests_at_the_close_minute_minus_one(self):
        assert policy_for(OrderType.ROD).on_no_fill(_order(), _ctx(13, 29)).cancel is False

    def test_cancels_at_the_close(self):
        d = policy_for(OrderType.ROD).on_no_fill(_order(), _ctx(13, 30))
        assert d.cancel is True
        assert "ROD expired" in d.reason

    def test_cancels_after_the_close(self):
        assert policy_for(OrderType.ROD).on_no_fill(_order(), _ctx(15)).cancel is True

    def test_expiry_is_keyed_on_the_order_s_own_day(self):
        """A missed 13:30 tick must still expire the order the next time we look."""
        order = _order(placed_at=MON.replace(hour=10))
        later = _ctx(9, 30, day=datetime(2025, 9, 2))     # next morning, pre-close
        assert policy_for(OrderType.ROD).on_no_fill(order, later).cancel is True

    def test_odd_lot_rod_lives_until_the_later_close(self):
        odd = _order(lot=OrderLot.IntraDayOdd)
        assert policy_for(OrderType.ROD).on_no_fill(odd, _ctx(13, 45)).cancel is False
        assert policy_for(OrderType.ROD).on_no_fill(odd, _ctx(14, 30)).cancel is True


# ── IOC / FOK / GTC ───────────────────────────────────────────────────────────

class TestImmediateOrCancel:
    def test_ioc_cancels_even_mid_session(self):
        d = policy_for(OrderType.IOC).on_no_fill(_order(OrderType.IOC), _ctx(11))
        assert d.cancel is True
        assert "IOC" in d.reason

    def test_fok_cancels_even_mid_session(self):
        d = policy_for(OrderType.FOK).on_no_fill(_order(OrderType.FOK), _ctx(11))
        assert d.cancel is True
        assert "FOK" in d.reason


class TestGTC:
    def test_survives_the_close(self):
        assert policy_for(OrderType.GTC).on_no_fill(_order(OrderType.GTC), _ctx(15)).cancel is False

    def test_survives_the_next_day(self):
        order = _order(OrderType.GTC, placed_at=MON.replace(hour=10))
        later = _ctx(11, 0, day=datetime(2025, 9, 8))
        assert policy_for(OrderType.GTC).on_no_fill(order, later).cancel is False


class TestPolicyLookup:
    def test_every_order_type_has_a_policy(self):
        for ot in OrderType:
            assert policy_for(ot) is not None

    def test_unknown_type_rests_rather_than_dies(self):
        assert policy_for("NOT_A_TYPE").on_no_fill(_order(), _ctx(11)).cancel is False


if __name__ == "__main__":
    pytest.main([__file__])
