"""Unit tests for _reconstruct_positions_from_history.

The thing under test is avg_cost: it must describe the lot still held, not the
average of every buy the account ever made. unrealized_pnl is derived from it,
so a wrong avg_cost is a wrong P&L on every caller that reads the position.
"""
import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_AccountState
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase


def _backend() -> ArenaX_BackendBase:
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
    b.account_state = ArenaX_AccountState()
    return b


def _fill(symbol: str, qty: int, price: float, time: str = "") -> dict:
    """One fill_history entry. quantity is signed: + BUY, - SELL."""
    return {"symbol": symbol, "quantity": qty, "price": price, "time": time}


def _positions(fills: list[dict]):
    b = _backend()
    b.account_state.fill_history = fills
    b._reconstruct_positions_from_history()
    return {p.symbol: p for p in b.account_state.positions}


class TestOpenLotCosting:
    def test_single_buy_costs_what_it_cost(self):
        pos = _positions([_fill("2317", 20, 240.0)])["2317"]
        assert pos.quantity == 20
        assert pos.avg_cost == pytest.approx(240.0)

    def test_fully_closed_position_disappears(self):
        assert _positions([
            _fill("2317", 20, 240.0),
            _fill("2317", -20, 250.0),
        ]) == {}

    def test_sell_retires_the_oldest_lot_first(self):
        # Buy 20@240, buy 20@260, sell 20. FIFO retires the 240 lot, so what
        # is held is the 260 lot. The old code averaged both and said 250.
        pos = _positions([
            _fill("2317", 20, 240.0),
            _fill("2317", 20, 260.0),
            _fill("2317", -20, 250.0),
        ])["2317"]
        assert pos.quantity == 20
        assert pos.avg_cost == pytest.approx(260.0)

    def test_partial_sell_leaves_the_remainder_of_one_lot(self):
        pos = _positions([
            _fill("2317", 20, 240.0),
            _fill("2317", -5, 250.0),
        ])["2317"]
        assert pos.quantity == 15
        assert pos.avg_cost == pytest.approx(240.0)

    def test_many_round_trips_do_not_drift_the_open_lot(self):
        """The regression this fix is for.

        Scalping around a rising price, then one lot left open. Lifetime
        averaging pulls avg_cost toward the mean traded price; FIFO reports the
        lot actually held.
        """
        fills = []
        for i in range(20):                       # 20 complete round trips
            px = 200.0 + i
            fills.append(_fill("2317", 10, px))
            fills.append(_fill("2317", -10, px + 1))
        fills.append(_fill("2317", 10, 300.0))    # the one still open

        pos = _positions(fills)["2317"]
        assert pos.quantity == 10
        assert pos.avg_cost == pytest.approx(300.0)
        # Lifetime average of all 21 buys would have been ~209.5.
        assert pos.avg_cost > 290.0

    def test_stacked_lots_average_only_what_is_held(self):
        pos = _positions([
            _fill("2317", 10, 240.0),
            _fill("2317", 10, 250.0),
            _fill("2317", 10, 260.0),
        ])["2317"]
        assert pos.quantity == 30
        assert pos.avg_cost == pytest.approx(250.0)   # (240+250+260)/3


class TestOrderingAndIsolation:
    def test_append_order_wins_over_timestamp_order(self):
        """_sync_with_real_account seeds openings with time="initial_sync".

        Sorting by `time` would place that string after every ISO timestamp and
        cost the seeded holding as the newest buy. Consume in append order.
        """
        pos = _positions([
            _fill("2317", 10, 100.0, time="initial_sync"),
            _fill("2317", 10, 300.0, time="2026-08-03T09:01:00"),
            _fill("2317", -10, 310.0, time="2026-08-03T10:01:00"),
        ])["2317"]
        # FIFO retires the seeded lot, leaving the 300 buy.
        assert pos.quantity == 10
        assert pos.avg_cost == pytest.approx(300.0)

    def test_symbols_are_costed_independently(self):
        out = _positions([
            _fill("2317", 10, 240.0),
            _fill("0050", 10, 50.0),
            _fill("2317", -10, 245.0),
        ])
        assert "2317" not in out
        assert out["0050"].avg_cost == pytest.approx(50.0)

    def test_empty_history_clears_positions(self):
        b = _backend()
        b.account_state.fill_history = []
        b._reconstruct_positions_from_history()
        assert b.account_state.positions == []


class TestOversell:
    def test_oversell_stays_visible_as_a_negative_quantity(self):
        """Reservation should prevent this; if it ever happens, say so.

        Dropping the position would erase the only evidence that fill_history
        went net-short in a cash equity account.
        """
        out = _positions([
            _fill("2317", 10, 240.0),
            _fill("2317", -30, 250.0),
        ])
        assert out["2317"].quantity == -20

    def test_sell_with_no_prior_buy_is_reported_not_ignored(self):
        out = _positions([_fill("2317", -10, 250.0)])
        assert out["2317"].quantity == -10


class TestMarketValuePlaceholder:
    def test_market_value_is_consistent_with_the_reported_cost(self):
        """Placeholder until _update_position_prices() re-marks it, but it must
        not contradict quantity x avg_cost in the meantime."""
        pos = _positions([
            _fill("2317", 20, 240.0),
            _fill("2317", 20, 260.0),
            _fill("2317", -20, 250.0),
        ])["2317"]
        assert pos.market_value == pytest.approx(pos.quantity * pos.avg_cost)
        assert pos.current_price == pytest.approx(pos.avg_cost)
