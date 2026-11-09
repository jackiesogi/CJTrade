"""Unit tests for ArenaX pre-trade checks — reservation of cash and shares."""
from datetime import datetime

import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.pkgs.models.cost import CostModel
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _backend(balance: float = 100_000.0) -> ArenaX_BackendBase:
    """Bare backend: no market, no disk, no network."""
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
    from cjtrade.apps.ArenaX.base_backend import ArenaX_AccountState
    b.account_state = ArenaX_AccountState()
    b.account_state.balance = balance
    b._cost_model = CostModel()
    return b


def _order(action=OrderAction.BUY, symbol="2317", qty=20, price=240.0) -> Order:
    return Order(
        product=Product(symbol=symbol), action=action, price=price, quantity=qty,
        price_type=PriceType.LMT, order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd, created_at=datetime(2025, 9, 1, 9, 1),
    )


def _hold(backend, symbol="2317", qty=20, cost=240.0):
    backend.account_state.positions = [Position(
        symbol=symbol, quantity=qty, avg_cost=cost,
        current_price=cost, market_value=qty * cost,
    )]


def _rest(backend, order):
    backend.account_state.orders_committed.append(order)


# ── Cash reservation ──────────────────────────────────────────────────────────

class TestBuyingPower:
    def test_no_resting_orders_leaves_balance_untouched(self):
        b = _backend(100_000.0)
        assert b.buying_power() == 100_000.0
        assert b._is_sufficient_account_balance(_order(qty=20)) is True

    def test_resting_buy_reserves_value_plus_commission(self):
        b = _backend(100_000.0)
        _rest(b, _order(qty=20, price=240.0))          # 4,800 + 20 minimum
        assert b.buying_power() == pytest.approx(100_000.0 - 4_820.0)

    def test_second_buy_that_would_overdraw_is_rejected(self):
        b = _backend(100_000.0)
        _rest(b, _order(qty=400, price=240.0))         # 96,000 + 136.8
        duplicate = _order(qty=400, price=240.0)
        # Used to pass: 100,000 >= 96,136.8. Both filling drove balance to -92,273.6
        assert b._is_sufficient_account_balance(duplicate) is False

    def test_smaller_buy_still_fits_in_what_is_left(self):
        b = _backend(100_000.0)
        _rest(b, _order(qty=20, price=240.0))          # reserves 4,820
        assert b._is_sufficient_account_balance(_order(qty=100, price=240.0)) is True

    def test_resting_sell_does_not_reserve_cash(self):
        b = _backend(100_000.0)
        _hold(b, qty=1000)
        _rest(b, _order(action=OrderAction.SELL, qty=400, price=240.0))
        assert b.buying_power() == 100_000.0

    def test_filled_and_cancelled_orders_reserve_nothing(self):
        b = _backend(100_000.0)
        b.account_state.orders_filled.append(_order(qty=400, price=240.0))
        b.account_state.orders_cancelled.append(_order(qty=400, price=240.0))
        assert b.buying_power() == 100_000.0


# ── Share reservation ─────────────────────────────────────────────────────────

class TestAvailableToSell:
    def test_no_resting_sells_exposes_whole_position(self):
        b = _backend()
        _hold(b, qty=20)
        assert b.available_to_sell("2317") == 20
        assert b._is_sufficient_account_inventory(_order(action=OrderAction.SELL, qty=20)) is True

    def test_duplicate_sell_is_rejected(self):
        b = _backend()
        _hold(b, qty=20)
        _rest(b, _order(action=OrderAction.SELL, qty=20))
        assert b.available_to_sell("2317") == 0
        # Used to pass: position.quantity (20) >= 20. Both filling left net -20.
        assert b._is_sufficient_account_inventory(_order(action=OrderAction.SELL, qty=20)) is False

    def test_partial_remainder_is_still_sellable(self):
        b = _backend()
        _hold(b, qty=20)
        _rest(b, _order(action=OrderAction.SELL, qty=15))
        assert b.available_to_sell("2317") == 5
        assert b._is_sufficient_account_inventory(_order(action=OrderAction.SELL, qty=5)) is True
        assert b._is_sufficient_account_inventory(_order(action=OrderAction.SELL, qty=6)) is False

    def test_no_position_cannot_sell(self):
        b = _backend()
        assert b.available_to_sell("2317") == 0
        assert b._is_sufficient_account_inventory(_order(action=OrderAction.SELL, qty=1)) is False

    def test_reservation_is_per_symbol(self):
        b = _backend()
        b.account_state.positions = [
            Position(symbol="2317", quantity=20, avg_cost=240.0,
                     current_price=240.0, market_value=4800.0),
            Position(symbol="2330", quantity=10, avg_cost=1000.0,
                     current_price=1000.0, market_value=10000.0),
        ]
        _rest(b, _order(action=OrderAction.SELL, symbol="2317", qty=20))
        assert b.available_to_sell("2317") == 0
        assert b.available_to_sell("2330") == 10

    def test_resting_buy_does_not_reserve_shares(self):
        b = _backend()
        _hold(b, qty=20)
        _rest(b, _order(action=OrderAction.BUY, qty=20))
        assert b.available_to_sell("2317") == 20


# ── orders_placed counts too (real_backend parks orders there) ────────────────

class TestPlacedStageIsReservedToo:
    def test_placed_buy_reserves_cash(self):
        b = _backend(100_000.0)
        b.account_state.orders_placed.append(_order(qty=400, price=240.0))
        assert b._is_sufficient_account_balance(_order(qty=400, price=240.0)) is False

    def test_placed_sell_reserves_shares(self):
        b = _backend()
        _hold(b, qty=20)
        b.account_state.orders_placed.append(_order(action=OrderAction.SELL, qty=20))
        assert b.available_to_sell("2317") == 0


if __name__ == "__main__":
    pytest.main([__file__])
