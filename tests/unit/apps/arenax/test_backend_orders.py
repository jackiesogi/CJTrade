"""Order lifecycle on a real historical backend: place, fill, settle, cancel, persist."""
from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.apps.ArenaX.backtest_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.base_backend import DEFAULT_INITIAL_BALANCE
from cjtrade.pkgs.marketdata import Capabilities
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product

MON = datetime(2025, 9, 1)          # Monday; the source serves Mon-Fri of this week


def at(h, m=0, day=0):
    return MON.replace(hour=h, minute=m) + timedelta(days=day)


def _close(ts: datetime) -> float:
    """100 all day, a dip to 95 at 10:00-10:29, a spike to 110 at 11:00-11:29."""
    minutes = ts.hour * 60 + ts.minute
    if 600 <= minutes < 630:
        return 95.0
    if 660 <= minutes < 690:
        return 110.0
    return 100.0


class _Source(MarketData):
    """Five sessions of 1m bars for any symbol, shaped by _close()."""
    name = "fake"

    @property
    def capabilities(self):
        return Capabilities(intervals=frozenset({"1m"}))

    def get_kbars(self, symbol, start, end, interval="1m"):
        self.require_interval(interval)
        start, end = to_window(start, end)
        bars = []
        for d in range(5):
            for m in range(1, 271):
                ts = at(9, day=d) + timedelta(minutes=m)
                c = _close(ts)
                bars.append(Kbar(ts, c, c, c, c, 1000, symbol))
        return in_window(bars, start, end)


class _FakeAccount:
    """Just enough AccountClient for seed_from_live."""
    def __init__(self, balance=50_000.0, positions=()):
        self._balance, self._positions = balance, list(positions)
        self.connected = False

    def is_connected(self):
        return self.connected

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def get_balance(self):
        return self._balance

    def get_positions(self):
        return self._positions


@pytest.fixture
def make_backend(tmp_path):
    def make(balance=100_000.0, now=at(9, 30), **kw):
        kw.setdefault("initial_balance", balance)
        b = ArenaX_Backend_Historical(
            market_data=_Source(), backtest_start_date=MON,
            price_db_path=str(tmp_path / "price.db"), state_dir=str(tmp_path / "states"),
            num_days_preload=3, **kw)
        assert b.login()
        b.market.set_market_time(now)
        return b
    return make


def _order(action=OrderAction.BUY, qty=10, price=96.0, order_type=OrderType.ROD,
           lot=OrderLot.Common, created_at=None, symbol="2330", **kw) -> Order:
    return Order(product=Product(symbol=symbol), action=action, price=price, quantity=qty,
                 price_type=PriceType.LMT, order_type=order_type, order_lot=lot,
                 created_at=created_at or at(9, 30), **kw)


def _status(b, o):
    return b.account_state.all_order_status.get(o.id)


def _buy_and_fill(b, qty=10, price=96.0):
    """Rest a BUY at 09:30 and step the clock across the 10:00 dip."""
    b.market.set_market_time(at(9, 30))
    o = _order(qty=qty, price=price)
    b.place_order(o)
    b.market.set_market_time(at(10, 15))
    b.sync_state(o.id)
    return o


class TestPlaceOrderValidation:
    @pytest.mark.parametrize("price", [0.0, -1.0])
    def test_a_non_positive_price_is_rejected(self, make_backend, price):
        b = make_backend()
        r = b.place_order(_order(price=price))
        assert r.status == OrderStatus.REJECTED
        assert "price" in r.message
        assert b.account_state.orders_committed == []

    @pytest.mark.parametrize("qty", [0, -5])
    def test_a_non_positive_quantity_is_rejected(self, make_backend, qty):
        b = make_backend()
        r = b.place_order(_order(qty=qty))
        assert r.status == OrderStatus.REJECTED
        assert "quantity" in r.message

    def test_a_buy_larger_than_the_balance_is_rejected(self, make_backend):
        b = make_backend(balance=1_000.0)
        r = b.place_order(_order(qty=10, price=96.0))      # 960 + 20 fits
        assert r.status != OrderStatus.REJECTED
        r = b.place_order(_order(qty=1, price=96.0))       # 20 left, needs 116
        assert r.status == OrderStatus.REJECTED
        assert "balance" in r.message

    def test_a_sell_without_shares_is_rejected(self, make_backend):
        b = make_backend()
        r = b.place_order(_order(action=OrderAction.SELL, price=108.0))
        assert r.status == OrderStatus.REJECTED
        assert "stock" in r.message

    def test_a_rejection_echoes_the_orders_opt_field(self, make_backend):
        b = make_backend()
        r = b.place_order(_order(price=0.0, opt_field={"session_id": "s1"}))
        assert r.metadata == {"session_id": "s1"}
        assert r.linked_order


class TestDailyTradingLimit:
    def test_orders_beyond_one_million_a_day_are_rejected(self, make_backend):
        b = make_backend(balance=5_000_000.0)
        assert b.place_order(_order(qty=6000, price=96.0)).status != OrderStatus.REJECTED
        r = b.place_order(_order(qty=5000, price=96.0))     # 576k + 480k > 1M
        assert r.status == OrderStatus.REJECTED
        assert "trading limit" in r.message

    def test_a_cancelled_order_frees_its_share_of_the_limit(self, make_backend):
        b = make_backend(balance=5_000_000.0)
        first = _order(qty=6000, price=96.0)
        b.place_order(first)
        b.cancel_order(first.id)
        assert b.place_order(_order(qty=5000, price=96.0)).status != OrderStatus.REJECTED

    def test_orders_created_on_another_day_do_not_count(self, make_backend):
        b = make_backend(balance=5_000_000.0)
        b.place_order(_order(qty=6000, price=96.0, order_type=OrderType.GTC,
                             created_at=at(9, 30, day=-3)))
        assert b.place_order(_order(qty=5000, price=96.0)).status != OrderStatus.REJECTED


class TestPlaceOrderAcceptance:
    def test_an_order_during_the_session_waits_for_matching(self, make_backend):
        b = make_backend()
        o = _order()
        r = b.place_order(o)
        assert r.status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert r.linked_order == o.id
        assert b.account_state.orders_committed == [o]

    def test_an_order_before_the_open_waits_for_the_market(self, make_backend):
        b = make_backend(now=at(8, 30))
        r = b.place_order(_order(order_type=OrderType.GTC, created_at=at(8, 30)))
        assert r.status == OrderStatus.COMMITTED_WAIT_MARKET_OPEN
        assert "market open" in r.message

    def test_an_order_never_fills_on_the_bar_it_was_placed_at(self, make_backend):
        b = make_backend(now=at(10, 5))                     # close is 95 right now
        o = _order(price=96.0, created_at=at(10, 5))
        assert b.place_order(o).status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert b.account_state.fill_history == []

    def test_placing_stamps_the_fill_window_start_at_the_simulated_time(self, make_backend):
        b = make_backend()
        o = _order()
        b.place_order(o)
        assert o.opt_field["last_check_for_fill"] == at(9, 30)


class TestFillAndSettlement:
    def test_a_buy_fills_on_the_first_bar_at_or_below_its_limit(self, make_backend):
        b = make_backend()
        o = _buy_and_fill(b)
        assert _status(b, o) == OrderStatus.FILLED
        assert b.account_state.fill_history[0]["time"] == at(10, 0).isoformat()

    def test_a_fill_is_booked_at_the_limit_not_the_bar_close(self, make_backend):
        b = make_backend()
        _buy_and_fill(b, qty=10, price=96.0)                # bar closed at 95
        assert b.account_state.fill_history[0]["price"] == 96.0
        assert b.account_state.balance == pytest.approx(100_000.0 - 960.0 - 20.0)

    def test_a_buy_does_not_fill_while_closes_stay_above_the_limit(self, make_backend):
        b = make_backend()
        o = _order(price=90.0)
        b.place_order(o)
        b.market.set_market_time(at(13, 0))
        assert b.sync_state(o.id).status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert b.account_state.balance == 100_000.0

    def test_a_round_trip_settles_cash_and_closes_the_position(self, make_backend):
        b = make_backend()
        _buy_and_fill(b, qty=10, price=96.0)
        sell = _order(action=OrderAction.SELL, qty=10, price=108.0, created_at=at(10, 15))
        assert b.place_order(sell).status == OrderStatus.COMMITTED_WAIT_MATCHING
        b.market.set_market_time(at(11, 10))
        b.sync_state(sell.id)
        assert _status(b, sell) == OrderStatus.FILLED
        # 1,080 - 20 commission - 3.24 tax, after paying 980
        assert b.account_state.balance == pytest.approx(100_000.0 - 980.0 + 1_056.76)
        assert b.list_positions() == []

    def test_open_positions_are_marked_to_the_bar_at_the_clock(self, make_backend):
        b = make_backend()
        _buy_and_fill(b, qty=10, price=96.0)
        b.market.set_market_time(at(11, 15))                # close 110
        pos = b.list_positions()[0]
        assert (pos.quantity, pos.avg_cost, pos.current_price) == (10, 96.0, 110.0)
        assert pos.market_value == 1_100.0
        assert pos.unrealized_pnl == 140.0

    def test_a_resting_sell_reserves_the_shares_it_will_deliver(self, make_backend):
        b = make_backend()
        _buy_and_fill(b, qty=10)
        assert b.place_order(_order(action=OrderAction.SELL, qty=10, price=200.0,
                                    created_at=at(10, 15))).status != OrderStatus.REJECTED
        r = b.place_order(_order(action=OrderAction.SELL, qty=1, price=200.0,
                                 created_at=at(10, 15)))
        assert r.status == OrderStatus.REJECTED

    def test_the_whole_quantity_fills_in_one_step(self, make_backend):
        b = make_backend()
        o = _buy_and_fill(b, qty=500, price=96.0)
        assert [f["quantity"] for f in b.account_state.fill_history] == [500]
        assert _status(b, o) == OrderStatus.FILLED


class TestTimeInForceOnPlacement:
    @pytest.mark.parametrize("ot", [OrderType.IOC, OrderType.FOK])
    def test_an_immediate_order_that_cannot_fill_is_cancelled(self, make_backend, ot):
        b = make_backend()
        o = _order(price=50.0, order_type=ot)
        assert b.place_order(o).status == OrderStatus.CANCELLED
        assert b.account_state.orders_cancelled == [o]
        assert b.buying_power() == b.account_state.balance

    def test_a_rod_left_unfilled_at_the_close_is_swept_by_list_trades(self, make_backend):
        b = make_backend()
        o = _order(price=50.0)
        b.place_order(o)
        b.market.set_market_time(at(13, 30))
        b.list_trades()
        assert _status(b, o) == OrderStatus.CANCELLED

    def test_expire_resting_orders_takes_an_explicit_moment(self, make_backend):
        b = make_backend()
        o = _order(price=50.0)
        b.place_order(o)
        assert b.expire_resting_orders(now=at(9, 45)) == []
        assert b.expire_resting_orders(now=at(14, 0)) == [o.id]

    def test_a_backend_without_a_market_expires_nothing(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        assert bare.expire_resting_orders() == []


class TestCancelOrder:
    def test_cancelling_a_resting_order_releases_its_cash(self, make_backend):
        b = make_backend()
        o = _order(qty=100, price=96.0)
        b.place_order(o)
        assert b.buying_power() < b.account_state.balance
        r = b.cancel_order(o.id)
        assert r.status == OrderStatus.CANCELLED
        assert b.account_state.orders_cancelled == [o]
        assert b.buying_power() == b.account_state.balance

    def test_cancelling_a_filled_order_is_rejected(self, make_backend):
        b = make_backend()
        o = _buy_and_fill(b)
        r = b.cancel_order(o.id)
        assert r.status == OrderStatus.REJECTED
        assert "filled" in r.message
        assert _status(b, o) == OrderStatus.FILLED

    def test_cancelling_an_unknown_order_is_rejected(self, make_backend):
        r = make_backend().cancel_order("nope")
        assert r.status == OrderStatus.REJECTED
        assert r.linked_order == "nope"

    def test_cancelling_twice_rejects_the_second_attempt(self, make_backend):
        b = make_backend()
        o = _order()
        b.place_order(o)
        b.cancel_order(o.id)
        assert b.cancel_order(o.id).status == OrderStatus.REJECTED
        assert b.account_state.orders_cancelled == [o]

    def test_an_order_in_the_placed_stage_can_be_cancelled(self, make_backend):
        b = make_backend()
        o = _order()
        b.account_state.orders_placed.append(o)
        assert b.cancel_order(o.id).status == OrderStatus.CANCELLED
        assert b.account_state.orders_placed == []


class TestSyncState:
    def test_a_resolved_order_reports_its_final_status(self, make_backend):
        b = make_backend()
        o = _order()
        b.place_order(o)
        b.cancel_order(o.id)
        r = b.sync_state(o.id)
        assert r.status == OrderStatus.CANCELLED
        assert r.message == "Order already resolved."

    def test_an_unknown_order_is_reported_not_found(self, make_backend):
        r = make_backend().sync_state("nope")
        assert r.status == OrderStatus.REJECTED
        assert "not found" in r.message


class TestListTrades:
    def test_every_stage_is_reported_with_its_status(self, make_backend):
        b = make_backend()
        filled = _buy_and_fill(b)
        resting = _order(price=50.0, order_type=OrderType.GTC, created_at=at(10, 15))
        cancelled = _order(price=50.0, created_at=at(10, 15))
        b.place_order(resting)
        b.place_order(cancelled)
        b.cancel_order(cancelled.id)
        got = {t.id: t for t in b.list_trades()}
        assert got[filled.id].status == "FILLED"
        assert got[resting.id].status == "COMMITTED_WAIT_MATCHING"
        assert got[cancelled.id].status == "CANCELLED"
        assert got[filled.id].order_datetime == "2025-09-01 09:30:00"
        assert got[resting.id].order_type == "GTC"

    def test_an_order_with_no_recorded_status_is_unknown(self, make_backend):
        b = make_backend()
        b.account_state.orders_placed.append(_order(order_type=OrderType.GTC))
        assert b.list_trades()[0].status == "UNKNOWN"


class TestFreshLogin:
    def test_the_initial_balance_is_the_starting_cash(self, make_backend):
        b = make_backend(balance=12_345.0)
        assert b.account_balance() == 12_345.0
        assert b.account_state.initial_balance == 12_345.0
        assert b.is_connected()

    def test_no_initial_balance_falls_back_to_the_default(self, make_backend):
        b = make_backend(initial_balance=0.0)
        assert b.account_balance() == DEFAULT_INITIAL_BALANCE
        assert b.account_state.initial_balance == DEFAULT_INITIAL_BALANCE

    def test_a_missing_snapshot_fails_the_login(self, tmp_path):
        b = ArenaX_Backend_Historical(
            market_data=_Source(), backtest_start_date=MON,
            price_db_path=str(tmp_path / "price.db"), state_dir=str(tmp_path),
            state_file=str(tmp_path / "missing.json"))
        assert b.login() is False
        assert b.is_connected() is False


class TestSnapshotRoundTrip:
    def test_logout_writes_a_new_snapshot_with_its_lineage(self, make_backend, tmp_path):
        b = make_backend(session_id="sess-a")
        _buy_and_fill(b)
        b.logout()
        assert not b.is_connected()
        data = json.loads((tmp_path / "states" / "sess-a.json").read_text())
        assert data["_meta"]["session_id"] == "sess-a"
        assert data["_meta"]["parent_session"] is None
        assert data["_meta"]["backend"] == "ArenaX_Backend_Historical"
        assert data["balance"] == pytest.approx(99_020.0)
        assert data["orders_filled"][0]["created_at"] == at(9, 30).isoformat()

    def test_resuming_restores_cash_positions_orders_and_statuses(self, make_backend):
        a = make_backend(session_id="parent")
        filled = _buy_and_fill(a)
        resting = _order(price=50.0, order_type=OrderType.GTC, created_at=at(10, 15))
        a.place_order(resting)
        a.logout()

        b = make_backend(state_file=a.state_out, session_id="child", initial_balance=0.0)
        assert b.account_balance() == pytest.approx(a.account_balance())
        assert b.account_state.initial_balance == pytest.approx(a.account_balance())
        assert [p.quantity for p in b.list_positions()] == [10]
        assert [o.id for o in b.account_state.orders_filled] == [filled.id]
        assert [o.id for o in b.account_state.orders_committed] == [resting.id]
        assert b.account_state.all_order_status[resting.id] == OrderStatus.COMMITTED_WAIT_MATCHING
        assert b.state_out != a.state_out

    def test_resuming_never_rewrites_the_snapshot_it_came_from(self, make_backend):
        a = make_backend(session_id="parent")
        a.logout()
        before = open(a.state_out).read()
        b = make_backend(state_file=a.state_out, session_id="child")
        _buy_and_fill(b)
        b.logout()
        assert open(a.state_out).read() == before
        assert json.load(open(b.state_out))["_meta"]["parent_session"] == a.state_out

    def test_an_unreadable_status_is_loaded_as_unknown(self, make_backend, tmp_path):
        path = tmp_path / "snap.json"
        path.write_text(json.dumps({"balance": 500.0, "all_order_status": {"x": "BOGUS"}}))
        b = make_backend(state_file=str(path), initial_balance=0.0)
        assert b.account_balance() == 500.0
        assert b.account_state.all_order_status == {"x": OrderStatus.UNKNOWN}

    @pytest.mark.parametrize("lot, expected", [(True, OrderLot.IntraDayOdd),
                                               (False, OrderLot.Common),
                                               ("Common", OrderLot.Common)])
    def test_a_legacy_boolean_order_lot_is_understood(self, lot, expected):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        o = bare._deserialize_order({"id": "o", "symbol": "2330", "action": "SELL",
                                     "price": 1.0, "quantity": 2, "order_lot": lot,
                                     "created_at": "2025-09-01T09:30:00"})
        assert o.order_lot == expected
        assert (o.id, o.action, o.created_at) == ("o", OrderAction.SELL, at(9, 30))


class TestSeedFromLive:
    def test_the_live_balance_and_holdings_seed_the_account(self, make_backend):
        live = _FakeAccount(balance=50_000.0, positions=[
            Position(symbol="2330", quantity=7, avg_cost=99.0,
                     current_price=99.0, market_value=693.0)])
        b = make_backend(seed_from_live=True, real_account=live, initial_balance=0.0)
        assert live.connected
        assert b.account_balance() == 50_000.0
        assert b.account_state.fill_history[0]["order_id"] == "manual_sync"
        pos = b.list_positions()[0]
        assert (pos.symbol, pos.quantity, pos.avg_cost) == ("2330", 7, 99.0)

    def test_an_empty_live_account_has_no_positions(self, make_backend):
        b = make_backend(seed_from_live=True, real_account=_FakeAccount(),
                         initial_balance=0.0)
        assert b.account_state.positions == []
        assert b.account_balance() == 50_000.0

    def test_seeding_is_ignored_without_a_live_account(self, make_backend):
        b = make_backend(seed_from_live=True, balance=1_000.0)
        assert b.account_balance() == 1_000.0


class TestKbars:
    def test_bars_after_the_simulated_clock_are_hidden(self, make_backend):
        b = make_backend(now=at(9, 30))
        bars = b.kbars("2330", "2025-09-01", "2025-09-01")
        assert len(bars) == 30
        assert bars[-1].timestamp == at(9, 30)

    def test_an_iso_datetime_window_is_half_open(self, make_backend):
        b = make_backend(now=at(13, 30))
        bars = b.kbars("2330", "2025-09-01T10:00:00", "2025-09-01T10:10:00")
        assert [k.timestamp.minute for k in bars] == list(range(10))

    def test_an_unparseable_date_returns_no_bars(self, make_backend):
        assert make_backend().kbars("2330", "yesterday", "2025-09-01") == []


class TestClockFallback:
    def test_without_a_market_the_wall_clock_is_used(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        before = datetime.now()
        assert before <= bare._clock() <= datetime.now()

    def test_a_snapshot_without_a_market_is_a_fallback_quote(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        snap = bare.snapshot("2330")
        assert snap.symbol == "2330"
        assert snap.low <= snap.close <= snap.high


class TestAggregateKbars:
    def _bars(self, n):
        return [Kbar(at(9, 0) + timedelta(minutes=i), 10 + i, 20 + i, 1 + i, 15 + i, 1, "2330")
                for i in range(n)]

    def test_minute_bars_roll_up_into_wider_bars(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        out = bare._aggregate_kbars_internal(self._bars(6), "3m")
        assert [k.timestamp for k in out] == [at(9, 0), at(9, 3)]
        first = out[0]
        assert (first.open, first.high, first.low, first.close, first.volume) == (10, 22, 1, 17, 3)
        assert first.symbol == "2330"

    def test_an_unsupported_interval_raises(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        with pytest.raises(ValueError, match="Unsupported interval"):
            bare._aggregate_kbars_internal(self._bars(3), "7m")

    def test_no_bars_aggregate_to_nothing(self):
        bare = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
        assert bare._aggregate_kbars_internal([], "3m") == []


if __name__ == "__main__":
    pytest.main([__file__])
