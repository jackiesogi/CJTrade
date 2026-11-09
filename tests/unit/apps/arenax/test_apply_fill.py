"""Unit tests for _apply_fill — the single settlement path for every backend."""
from datetime import datetime

import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_AccountState
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.paper_backend import ArenaX_Backend_PaperTrade
from cjtrade.apps.ArenaX.real_backend import ArenaX_Backend_RealTrade
from cjtrade.pkgs.models.cost import CostModel
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

FILL_TIME = datetime(2025, 9, 1, 10, 30)


def _backend(balance: float = 100_000.0) -> ArenaX_BackendBase:
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
    b.account_state = ArenaX_AccountState()
    b.account_state.balance = balance
    b._cost_model = CostModel()
    return b


def _order(action=OrderAction.BUY, qty=20, price=240.0, opt=None) -> Order:
    return Order(
        product=Product(symbol="2317"), action=action, price=price, quantity=qty,
        price_type=PriceType.LMT, order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd, created_at=datetime(2025, 9, 1, 9, 1),
        opt_field=opt or {},
    )


class TestApplyFill:
    def test_buy_pays_value_plus_commission(self):
        b = _backend(100_000.0)
        o = _order(qty=20, price=240.0)
        b.account_state.orders_committed.append(o)
        assert b._apply_fill(o, 240.0, FILL_TIME) is True
        # 4,800 + max(6.84, 20) = 4,820
        assert b.account_state.balance == pytest.approx(95_180.0)

    def test_sell_receives_value_less_commission_and_tax(self):
        b = _backend(0.0)
        o = _order(action=OrderAction.SELL, qty=20, price=240.0)
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        # 4,800 - 20 commission - 14.4 tax (0.3%)
        assert b.account_state.balance == pytest.approx(4_765.6)

    def test_etf_pays_the_lower_tax_rate(self):
        b = _backend(0.0)
        o = _order(action=OrderAction.SELL, qty=20, price=240.0)
        o.product = Product(symbol="0050")
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        # 0.1% for ETFs: 4,800 - 20 - 4.8
        assert b.account_state.balance == pytest.approx(4_775.2)

    def test_moves_the_order_and_sets_the_status(self):
        b = _backend()
        o = _order()
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        assert b.account_state.orders_committed == []
        assert b.account_state.orders_filled == [o]
        assert b.account_state.all_order_status[o.id] == OrderStatus.FILLED

    def test_also_clears_the_placed_stage(self):
        """real_backend parks orders in orders_placed, not orders_committed."""
        b = _backend()
        o = _order()
        b.account_state.orders_placed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        assert b.account_state.orders_placed == []
        assert b.account_state.orders_filled == [o]

    def test_records_costs_and_session_id_in_fill_history(self):
        b = _backend()
        o = _order(opt={"session_id": "sess-1"})
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        fill = b.account_state.fill_history[0]
        assert fill["session_id"] == "sess-1"
        assert fill["commission"] == 20.0
        assert fill["tax"] == 0.0            # BUY pays no tax
        assert fill["time"] == FILL_TIME.isoformat()
        assert fill["quantity"] == 20        # positive for BUY

    def test_sell_is_recorded_with_a_negative_quantity(self):
        b = _backend()
        o = _order(action=OrderAction.SELL)
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        assert b.account_state.fill_history[0]["quantity"] == -20

    def test_fill_price_may_differ_from_the_limit_price(self):
        b = _backend(100_000.0)
        o = _order(qty=20, price=240.0)
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 238.0, FILL_TIME)      # broker filled better
        assert b.account_state.fill_history[0]["price"] == 238.0
        assert b.account_state.balance == pytest.approx(100_000.0 - (4_760.0 + 20.0))

    def test_position_is_rebuilt_from_history(self):
        b = _backend()
        o = _order(qty=20, price=240.0)
        b.account_state.orders_committed.append(o)
        b._apply_fill(o, 240.0, FILL_TIME)
        pos = next(p for p in b.account_state.positions if p.symbol == "2317")
        assert pos.quantity == 20
        assert pos.avg_cost == 240.0

    def test_reservation_is_released_by_the_fill(self):
        b = _backend(100_000.0)
        o = _order(qty=400, price=240.0)
        b.account_state.orders_committed.append(o)
        assert b.buying_power() < 100_000.0
        b._apply_fill(o, 240.0, FILL_TIME)
        assert b.buying_power() == b.account_state.balance


class TestEveryBackendSharesIt:
    def test_paper_and_real_do_not_define_their_own(self):
        base = ArenaX_BackendBase._apply_fill
        assert ArenaX_Backend_PaperTrade._apply_fill is base
        assert ArenaX_Backend_RealTrade._apply_fill is base


if __name__ == "__main__":
    pytest.main([__file__])
