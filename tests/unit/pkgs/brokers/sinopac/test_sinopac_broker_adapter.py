"""Unit tests for SinopacBrokerAPI against a fake shioaji session.

`sj.Shioaji` is replaced by FakeShioaji before construction, so no login,
certificate or network is ever reached. The fake records what the adapter
sends, which is how these tests check that a CJ order reaches the broker
with the right side, price type, time in force and lot.
"""
import itertools
import time
import types
from datetime import datetime

import pytest
import shioaji as sj
from cjtrade.pkgs.brokers.sinopac import sinopac_broker_api as mod
from cjtrade.pkgs.brokers.sinopac._internal_func import cj_sj_order_map
from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import get_bkr_order_id_from_db
from cjtrade.pkgs.db.db_api import insert_new_order_to_db
from cjtrade.pkgs.db.db_api import insert_new_ordermap_item_to_db
from cjtrade.pkgs.db.db_api import prepare_cjtrade_tables
from cjtrade.pkgs.models.event import EventType
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType
from cjtrade.pkgs.models.rank_type import RankType
from cjtrade.pkgs.models.trade import Trade

NS = types.SimpleNamespace
Status = sj.constant.Status
CREDS = dict(api_key="fake-key", secret_key="fake-secret", ca_path="fake.pfx", ca_passwd="fake-pw")


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeQuote:
    def __init__(self, deliver=None):
        self.deliver = deliver          # bidask pushed on subscribe, or None
        self.callback = None
        self.subscribed = []
        self.unsubscribed = []

    def set_on_bidask_stk_v1_callback(self, cb):
        self.callback = cb

    def subscribe(self, contract, **kwargs):
        self.subscribed.append((contract, kwargs))
        if self.deliver is not None:
            self.callback("TSE", self.deliver)

    def unsubscribe(self, contract, **kwargs):
        self.unsubscribed.append((contract, kwargs))


class FakeShioaji:
    """The subset of shioaji.Shioaji the adapter touches; records every call."""

    def __init__(self, simulation=True):
        self.simulation = simulation
        self.calls = []
        self.stock_account = NS(account_id="FAKE-ACC")
        self.Contracts = NS(Stocks={
            "2330": NS(code="2330", exchange=sj.constant.Exchange.TSE),
            "0050": NS(code="0050", exchange=sj.constant.Exchange.TSE),
        })
        self.quote = FakeQuote()
        self.trades = []
        self.next_trade = None
        self.positions = []
        self.balance = NS(acc_balance=123456.0)
        self.snapshot_rows = {}
        self.movers = []
        self.order_callback = None
        self.fail = {}                  # method name -> exception to raise

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.fail:
            raise self.fail[name]

    def names(self):
        return [c[0] for c in self.calls]

    def login(self, **kwargs):
        self._record("login", **kwargs)

    def activate_ca(self, **kwargs):
        self._record("activate_ca", **kwargs)

    def logout(self):
        self._record("logout")

    def place_order(self, contract, order):
        self._record("place_order", contract, order)
        return self.next_trade

    def cancel_order(self, trade):
        self._record("cancel_order", trade)

    def update_status(self, *args):
        self._record("update_status", *args)

    def list_trades(self):
        self._record("list_trades")
        return self.trades

    def list_positions(self, **kwargs):
        self._record("list_positions", **kwargs)
        return self.positions

    def account_balance(self):
        self._record("account_balance")
        return self.balance

    def snapshots(self, contracts):
        self._record("snapshots", contracts)
        return [self.snapshot_rows[c.code] for c in contracts]

    def scanners(self, **kwargs):
        self._record("scanners", **kwargs)
        return self.movers

    def set_order_callback(self, cb):
        self._record("set_order_callback", cb)
        self.order_callback = cb


def sj_trade(sj_id="sj1", status=Status.Submitted, seqno="000001", code="2330", **order_fields):
    order = dict(id=sj_id, seqno=seqno, ordno="A0001", action=sj.constant.Action.Buy,
                 price=500.0, quantity=3, price_type=sj.constant.StockPriceType.LMT,
                 order_type=sj.constant.OrderType.ROD, order_lot=sj.constant.StockOrderLot.IntradayOdd)
    order.update(order_fields)
    return NS(
        contract=NS(code=code),
        order=NS(**order),
        status=NS(id=sj_id, status=status, deals=[],
                  order_datetime=datetime(2026, 1, 5, 9, 30, 15)),
    )


def make_order(action=OrderAction.BUY, order_type=OrderType.ROD, symbol="2330", **kw):
    fields = dict(price=500.0, quantity=3, price_type=PriceType.LMT, order_lot=OrderLot.IntraDayOdd)
    fields.update(kw)
    return Order(product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol=symbol),
                 action=action, order_type=order_type, **fields)


def order_status_in_db(db, oid):
    rows = db.execute("SELECT status FROM orders WHERE order_id = ?", (oid,))
    return rows[0][0] if rows else None


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_real_shioaji(monkeypatch):
    monkeypatch.setattr(sj, "Shioaji", FakeShioaji)
    cj_sj_order_map.clear()
    yield
    cj_sj_order_map.clear()


@pytest.fixture
def tmp_db(tmp_path):
    conn = connect_sqlite(database=str(tmp_path / "mirror.db"))
    prepare_cjtrade_tables(conn)
    yield conn
    conn.close()


@pytest.fixture
def broker(tmp_path, tmp_db):
    """A connected adapter over FakeShioaji and a temp mirror DB."""
    b = SinopacBrokerAPI(mirror_db_path=str(tmp_path / "unused.db"), **CREDS)
    b.db = tmp_db
    b._connected = True
    return b


@pytest.fixture
def offline(tmp_path):
    return SinopacBrokerAPI(mirror_db_path=str(tmp_path / "mirror.db"), **CREDS)


# ── Construction and session ──────────────────────────────────────────────────

class TestConstruction:
    @pytest.mark.parametrize("missing", ["api_key", "secret_key", "ca_path", "ca_passwd"])
    def test_each_required_credential_is_checked(self, missing):
        config = {k: v for k, v in CREDS.items() if k != missing}
        with pytest.raises(ValueError, match=missing):
            SinopacBrokerAPI(**config)

    def test_simulation_is_on_by_default_and_passed_to_shioaji(self, offline):
        assert offline.simulation is True
        assert offline.api.simulation is True

    def test_simulation_false_is_passed_through_to_shioaji(self, tmp_path):
        b = SinopacBrokerAPI(simulation=False, mirror_db_path=str(tmp_path / "m.db"), **CREDS)
        assert b.api.simulation is False

    def test_a_new_adapter_is_disconnected_with_the_default_username(self, offline):
        assert offline.is_connected() is False
        assert offline.username == "user999"
        assert offline.db is None
        assert offline.api.calls == []          # nothing is sent at construction

    def test_the_broker_name_is_sinopac(self, offline):
        assert offline.get_broker_name() == "sinopac"

    def test_market_data_wraps_this_adapter(self, offline):
        assert offline.market_data().broker is offline

    def test_market_time_is_wall_clock_at_normal_speed(self, offline):
        t = offline.get_market_time()
        assert t["mock_current_time"] == t["real_current_time"]
        assert t["mock_init_time"] == t["real_init_time"] == offline._session_start
        assert t["playback_speed"] == 1.0
        assert t["paused"] is False


class TestConnect:
    def test_connect_logs_in_activates_the_ca_and_opens_the_mirror_db(self, offline, tmp_path):
        assert offline.connect() is True
        assert offline.is_connected()
        login, ca = offline.api.calls[:2]
        assert login == ("login", (), {"api_key": "fake-key", "secret_key": "fake-secret"})
        assert ca == ("activate_ca", (), {"ca_path": "fake.pfx", "ca_passwd": "fake-pw"})
        assert (tmp_path / "mirror.db").exists()
        # Tables exist: the order map is queryable.
        assert offline.db.execute("SELECT * FROM CJ_OrderMap") == []
        offline.db.close()

    def test_connecting_twice_does_not_log_in_again(self, offline):
        offline._connected = True
        assert offline.connect() is True
        assert offline.api.calls == []

    @pytest.mark.parametrize("step", ["login", "activate_ca"])
    def test_a_failed_login_step_returns_false_and_stays_disconnected(self, offline, step):
        offline.api.fail[step] = RuntimeError("bad cert")
        assert offline.connect() is False
        assert offline.is_connected() is False


class TestDisconnect:
    def test_disconnect_logs_out_and_closes_the_db(self, broker):
        closed = []
        broker.db = NS(close=lambda: closed.append(True))
        broker.disconnect()
        assert broker.api.names() == ["logout"]
        assert closed == [True]
        assert broker.is_connected() is False

    def test_a_logout_error_still_closes_the_db_and_disconnects(self, broker):
        closed = []
        broker.db = NS(close=lambda: closed.append(True))
        broker.api.fail["logout"] = RuntimeError("pybind11 error_already_set")
        broker.disconnect()
        assert closed == [True]
        assert broker.is_connected() is False

    def test_a_db_close_error_still_disconnects(self, broker):
        def boom():
            raise OSError("disk gone")
        broker.db = NS(close=boom)
        broker.disconnect()
        assert broker.is_connected() is False

    def test_disconnecting_when_not_connected_does_nothing(self, offline):
        offline.disconnect()
        assert offline.api.calls == []


class TestNotConnected:
    """Every network method refuses before touching the SDK."""

    @pytest.mark.parametrize("call", [
        lambda b: b.get_bid_ask(Product(symbol="2330")),
        lambda b: b.get_snapshots([Product(symbol="2330")]),
        lambda b: b.get_market_movers(),
        lambda b: b.place_order(make_order()),
        lambda b: b.sync_state(),
        lambda b: b.cancel_order("cj1"),
        lambda b: b.list_orders(),
    ])
    def test_the_call_raises_connection_error_without_any_api_call(self, offline, call):
        with pytest.raises(ConnectionError):
            call(offline)
        assert offline.api.calls == []


# ── Account data ──────────────────────────────────────────────────────────────

class TestGetPositions:
    def test_positions_are_requested_in_shares(self, broker):
        broker.get_positions()
        assert broker.api.calls == [("list_positions", (), {"unit": sj.constant.Unit.Share})]

    def test_each_shioaji_position_becomes_a_cj_position(self, broker):
        broker.api.positions = [
            NS(code="2330", quantity=30, price=500.0, last_price=520.0, pnl=600.0),
            NS(code="0050", quantity=100, price=150.0, last_price=140.0, pnl=-1000.0),
        ]
        first, second = broker.get_positions()
        assert (first.symbol, first.quantity, first.avg_cost, first.current_price) == \
            ("2330", 30, 500.0, 520.0)
        assert first.market_value == 30 * 520.0
        assert first.unrealized_pnl == 600.0
        assert second.unrealized_pnl == -1000.0

    def test_an_empty_account_gives_no_positions(self, broker):
        assert broker.get_positions() == []

    def test_an_sdk_error_gives_an_empty_list(self, broker):
        broker.api.fail["list_positions"] = RuntimeError("timeout")
        assert broker.get_positions() == []

    def test_a_position_missing_a_field_gives_an_empty_list(self, broker):
        broker.api.positions = [NS(code="2330", quantity=1, price=1.0)]   # no last_price
        assert broker.get_positions() == []


class TestGetBalance:
    def test_the_balance_is_the_account_balance_field(self, broker):
        assert broker.get_balance() == 123456.0

    def test_an_sdk_error_propagates(self, broker):
        broker.api.fail["account_balance"] = RuntimeError("timeout")
        with pytest.raises(RuntimeError):
            broker.get_balance()


# ── Market data ───────────────────────────────────────────────────────────────

class TestGetBidAsk:
    def quote(self):
        return NS(code="2330", datetime=datetime(2026, 1, 5, 10, 0),
                  bid_price=[600, 599.5], bid_volume=[1, 2],
                  ask_price=[600.5], ask_volume=[3])

    def test_the_first_pushed_quote_is_returned_and_the_feed_unsubscribed(self, broker):
        broker.api.quote.deliver = self.quote()
        book = broker.get_bid_ask(Product(symbol="2330"))
        assert book.symbol == "2330"
        assert book.bid_price == [600.0, 599.5]
        contract = broker.api.Contracts.Stocks["2330"]
        expected = {"quote_type": sj.constant.QuoteType.BidAsk, "version": sj.constant.QuoteVersion.v1}
        assert broker.api.quote.subscribed == [(contract, expected)]
        assert broker.api.quote.unsubscribed == [(contract, expected)]

    def test_intraday_odd_subscribes_to_the_odd_lot_book(self, broker):
        broker.api.quote.deliver = self.quote()
        broker.get_bid_ask(Product(symbol="2330"), intraday_odd=True)
        (_, kwargs), = broker.api.quote.subscribed
        assert kwargs["intraday_odd"] is True
        assert broker.api.quote.unsubscribed[0][1]["intraday_odd"] is True

    def test_no_quote_within_the_timeout_returns_none_after_unsubscribing(self, broker, monkeypatch):
        # A clock that advances one second per read ends the 5 s wait at once.
        clock = itertools.count(0.0, 1.0)
        monkeypatch.setattr(time, "time", lambda: next(clock))
        monkeypatch.setattr(time, "sleep", lambda s: None)
        assert broker.get_bid_ask(Product(symbol="2330")) is None
        assert len(broker.api.quote.unsubscribed) == 1

    def test_an_unknown_symbol_raises_before_subscribing(self, broker):
        with pytest.raises(ValueError):
            broker.get_bid_ask(Product(symbol="9999"))
        assert broker.api.quote.subscribed == []


class TestGetSnapshots:
    def setup_rows(self, broker):
        broker.api.snapshot_rows = {
            "2330": NS(code="2330", close=600.0, ts=0),
            "0050": NS(code="0050", close=150.0, ts=0),
        }

    def test_each_product_becomes_a_snapshot_in_order(self, broker, monkeypatch):
        self.setup_rows(broker)
        monkeypatch.setattr(broker, "is_market_open", lambda: True)
        snaps = broker.get_snapshots([Product(symbol="0050"), Product(symbol="2330")])
        assert [(s.symbol, s.close) for s in snaps] == [("0050", 150.0), ("2330", 600.0)]

    def test_while_the_market_is_open_every_call_hits_the_api_and_clears_the_cache(self, broker, monkeypatch):
        self.setup_rows(broker)
        broker._cached_closed_prices = {("old",): []}
        monkeypatch.setattr(broker, "is_market_open", lambda: True)
        broker.get_snapshots([Product(symbol="2330")])
        broker.get_snapshots([Product(symbol="2330")])
        assert broker.api.names().count("snapshots") == 2
        assert broker._cached_closed_prices == {}

    def test_while_the_market_is_closed_the_same_symbols_are_fetched_once(self, broker, monkeypatch):
        self.setup_rows(broker)
        monkeypatch.setattr(broker, "is_market_open", lambda: False)
        first = broker.get_snapshots([Product(symbol="2330")])
        second = broker.get_snapshots([Product(symbol="2330")])
        assert first is second
        assert broker.api.names().count("snapshots") == 1

    def test_while_the_market_is_closed_a_different_symbol_set_is_fetched(self, broker, monkeypatch):
        self.setup_rows(broker)
        monkeypatch.setattr(broker, "is_market_open", lambda: False)
        broker.get_snapshots([Product(symbol="2330")])
        broker.get_snapshots([Product(symbol="2330"), Product(symbol="0050")])
        assert broker.api.names().count("snapshots") == 2


class TestIsMarketOpen:
    @pytest.mark.parametrize("now, is_open", [
        (datetime(2026, 1, 5, 8, 59, 59), False),     # Monday, before open
        (datetime(2026, 1, 5, 9, 0, 0), True),
        (datetime(2026, 1, 5, 11, 0, 0), True),
        (datetime(2026, 1, 5, 13, 30, 0), True),
        (datetime(2026, 1, 5, 13, 30, 1), False),
        (datetime(2026, 1, 9, 10, 0, 0), True),        # Friday
        (datetime(2026, 1, 10, 10, 0, 0), False),      # Saturday
        (datetime(2026, 1, 11, 10, 0, 0), False),      # Sunday
    ])
    def test_open_only_on_weekdays_from_nine_to_thirteen_thirty(self, broker, monkeypatch, now, is_open):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        monkeypatch.setattr(mod, "datetime", FixedDatetime)
        assert broker.is_market_open() is is_open


class TestGetMarketMovers:
    def test_the_scanner_is_asked_with_the_mapped_rank_and_count(self, broker, monkeypatch):
        monkeypatch.setattr(broker, "is_market_open", lambda: True)
        broker.get_market_movers(top_n=5, by=RankType.VOLUME, ascending=False)
        assert broker.api.calls[0] == ("scanners", (), {
            "scanner_type": sj.constant.ScannerType.VolumeRank, "ascending": False, "count": 5})

    def test_movers_are_keyed_by_name_with_the_name_on_the_snapshot(self, broker, monkeypatch):
        monkeypatch.setattr(broker, "is_market_open", lambda: True)
        broker.api.movers = [NS(code="2330", name="TSMC"), NS(code="0050", name="ETF50")]
        broker.api.snapshot_rows = {"2330": NS(code="2330", close=600.0),
                                    "0050": NS(code="0050", close=150.0)}
        movers = broker.get_market_movers()
        assert list(movers) == ["TSMC", "ETF50"]
        assert movers["TSMC"].symbol == "2330"
        assert movers["ETF50"].name == "ETF50"

    def test_a_scanner_error_is_raised_as_value_error(self, broker):
        broker.api.fail["scanners"] = RuntimeError("rate limited")
        with pytest.raises(ValueError, match="Cannot get market movers"):
            broker.get_market_movers()


# ── Orders ────────────────────────────────────────────────────────────────────

class TestPlaceOrder:
    """place_order converts, submits, and records the CJ <-> shioaji id mapping."""

    def sent(self, broker):
        (name, (contract, sj_order), _), = [c for c in broker.api.calls if c[0] == "place_order"]
        return contract, sj_order

    def test_a_buy_reaches_shioaji_as_a_buy_with_the_same_terms(self, broker):
        broker.api.next_trade = sj_trade(status=Status.PendingSubmit)
        broker.place_order(make_order(action=OrderAction.BUY, price=31.65, quantity=2))
        contract, sj_order = self.sent(broker)
        assert contract is broker.api.Contracts.Stocks["2330"]
        assert sj_order.action == sj.constant.Action.Buy
        assert sj_order.price == 31.65
        assert sj_order.quantity == 2
        assert sj_order.price_type == sj.constant.StockPriceType.LMT
        assert sj_order.order_type == sj.constant.OrderType.ROD
        assert sj_order.order_lot == sj.constant.StockOrderLot.IntradayOdd

    def test_a_sell_market_ioc_common_lot_order_is_sent_as_such(self, broker):
        broker.api.next_trade = sj_trade()
        broker.place_order(make_order(action=OrderAction.SELL, price_type=PriceType.MKT,
                                      order_type=OrderType.IOC, order_lot=OrderLot.Common))
        _, sj_order = self.sent(broker)
        assert sj_order.action == sj.constant.Action.Sell
        assert sj_order.price_type == sj.constant.StockPriceType.MKT
        assert sj_order.order_type == sj.constant.OrderType.IOC
        assert sj_order.order_lot == sj.constant.StockOrderLot.Common

    def test_the_result_carries_the_shioaji_status_and_links_the_cj_order_id(self, broker):
        broker.api.next_trade = sj_trade(sj_id="sjX", status=Status.PendingSubmit)
        order = make_order()
        result = broker.place_order(order)
        assert result.status == OrderStatus.PLACED
        assert result.linked_order == order.id

    def test_the_trade_is_cached_and_the_id_mapping_persisted(self, broker):
        trade = sj_trade(sj_id="sjX")
        broker.api.next_trade = trade
        order = make_order()
        broker.place_order(order)
        assert cj_sj_order_map[order.id] is trade
        assert get_bkr_order_id_from_db(conn=broker.db, cj_order_id=order.id) == "sjX"

    def test_the_order_is_recorded_locally_as_placed(self, broker):
        broker.api.next_trade = sj_trade()
        order = make_order()
        broker.place_order(order)
        assert order_status_in_db(broker.db, order.id) == "PLACED"

    def test_a_gtc_order_raises_before_reaching_shioaji(self, broker):
        with pytest.raises(NotImplementedError):
            broker.place_order(make_order(order_type=OrderType.GTC))
        assert broker.api.calls == []

    def test_an_unknown_symbol_is_rejected_without_sending(self, broker):
        result = broker.place_order(make_order(symbol="9999"))
        assert result.status == OrderStatus.REJECTED
        assert "Cannot resolve Sinopac contract" in result.message
        assert "place_order" not in broker.api.names()

    def test_an_unsupported_action_is_rejected_without_sending(self, broker):
        result = broker.place_order(make_order(action=OrderAction.CANCEL))
        assert result.status == OrderStatus.REJECTED
        assert "place_order" not in broker.api.names()

    def test_a_response_without_an_order_id_is_rejected_and_nothing_is_recorded(self, broker):
        broker.api.next_trade = None
        order = make_order()
        result = broker.place_order(order)
        assert result.status == OrderStatus.REJECTED
        assert result.linked_order == ""
        assert order.id not in cj_sj_order_map
        assert order_status_in_db(broker.db, order.id) is None


class TestSyncState:
    def track(self, broker, cj_id, trade):
        cj_sj_order_map[cj_id] = trade
        insert_new_order_to_db(conn=broker.db, username="u", order=make_order(id=cj_id))

    def test_the_stock_account_status_is_refreshed_first(self, broker):
        broker.sync_state()
        assert broker.api.calls[0] == ("update_status", (broker.api.stock_account,), {})

    def test_only_open_orders_are_returned(self, broker):
        open_statuses = [Status.PendingSubmit, Status.PreSubmitted, Status.Submitted, Status.PartFilled]
        final_statuses = [Status.Filled, Status.Cancelled, Status.Failed]
        for i, status in enumerate(open_statuses + final_statuses):
            self.track(broker, f"cj{i}", sj_trade(sj_id=f"sj{i}", status=status))
        results = broker.sync_state()
        assert sorted(r.linked_order for r in results) == ["sj0", "sj1", "sj2", "sj3"]
        assert [r.status for r in results] == [
            OrderStatus.PLACED, OrderStatus.COMMITTED_WAIT_MARKET_OPEN,
            OrderStatus.COMMITTED_WAIT_MATCHING, OrderStatus.PARTIAL]

    def test_open_orders_have_their_status_written_to_the_db(self, broker):
        self.track(broker, "cjA", sj_trade(sj_id="sjA", status=Status.PartFilled))
        self.track(broker, "cjB", sj_trade(sj_id="sjB", status=Status.Filled))
        broker.sync_state()
        assert order_status_in_db(broker.db, "cjA") == "PARTIAL"
        assert order_status_in_db(broker.db, "cjB") == "PLACED"   # final ones are skipped

    def test_an_sdk_error_returns_a_single_rejected_result(self, broker):
        broker.api.fail["update_status"] = RuntimeError("session expired")
        result = broker.sync_state()
        assert isinstance(result, OrderResult)
        assert result.status == OrderStatus.REJECTED
        assert result.metadata["error"] == "session expired"


class TestCancelOrder:
    def test_an_open_order_is_cancelled_and_marked_in_the_db(self, broker):
        trade = sj_trade(status=Status.Submitted)
        cj_sj_order_map["cj1"] = trade
        insert_new_order_to_db(conn=broker.db, username="u", order=make_order(id="cj1"))
        result = broker.cancel_order("cj1")
        assert ("cancel_order", (trade,), {}) in broker.api.calls
        assert broker.api.names().count("update_status") == 2    # before and after
        assert order_status_in_db(broker.db, "cj1") == "CANCELLED"
        assert result.linked_order == "sj1"

    def test_the_result_reflects_the_trade_status_after_the_refresh(self, broker):
        trade = sj_trade(status=Status.Submitted)
        cj_sj_order_map["cj1"] = trade
        broker.api.cancel_order = lambda t: setattr(t.status, "status", Status.Cancelled)
        assert broker.cancel_order("cj1").status == OrderStatus.CANCELLED

    def test_an_order_known_only_from_the_db_is_found_via_list_trades(self, broker):
        trade = sj_trade(sj_id="sj9")
        broker.api.trades = [trade]
        insert_new_ordermap_item_to_db(conn=broker.db, cj_order_id="cj9",
                                       bkr_order_id="sj9", broker="sinopac")
        broker.cancel_order("cj9")
        assert ("cancel_order", (trade,), {}) in broker.api.calls

    def test_an_unknown_order_is_rejected_without_cancelling(self, broker):
        result = broker.cancel_order("ghost")
        assert result.status == OrderStatus.REJECTED
        assert "not found" in result.message
        assert result.linked_order == "ghost"
        assert "cancel_order" not in broker.api.names()

    @pytest.mark.parametrize("final", [Status.Filled, Status.Cancelled, Status.Failed])
    def test_an_order_in_a_final_state_is_rejected_without_cancelling(self, broker, final):
        cj_sj_order_map["cj1"] = sj_trade(status=final)
        result = broker.cancel_order("cj1")
        assert result.status == OrderStatus.REJECTED
        assert "already" in result.message
        assert "cancel_order" not in broker.api.names()

    def test_an_sdk_cancel_error_is_rejected_and_the_db_left_alone(self, broker):
        cj_sj_order_map["cj1"] = sj_trade(status=Status.Submitted)
        insert_new_order_to_db(conn=broker.db, username="u", order=make_order(id="cj1"))
        broker.api.fail["cancel_order"] = RuntimeError("exchange closed")
        result = broker.cancel_order("cj1")
        assert result.status == OrderStatus.REJECTED
        assert result.metadata["error"] == "exchange closed"
        assert order_status_in_db(broker.db, "cj1") == "PLACED"


class TestListOrders:
    def test_status_is_refreshed_before_listing(self, broker):
        broker.list_orders()
        assert broker.api.names() == ["update_status", "list_trades"]

    def test_a_shioaji_trade_becomes_a_cj_trade(self, broker):
        broker.api.trades = [sj_trade(sj_id="sj1", status=Status.PartFilled, price=31.5, quantity=4)]
        broker.api.trades[0].status.deals = [NS(), NS()]
        insert_new_ordermap_item_to_db(conn=broker.db, cj_order_id="cj1",
                                       bkr_order_id="sj1", broker="sinopac")
        (t,) = broker.list_orders()
        assert isinstance(t, Trade)
        assert (t.id, t.symbol, t.quantity, t.price) == ("cj1", "2330", 4, 31.5)
        assert t.status == "PARTIAL"
        assert (t.order_type, t.price_type) == ("ROD", "LMT")
        assert t.order_datetime == "2026-01-05 09:30:15"
        assert t.deals == 2
        assert t.ordno == "A0001"

    def test_a_trade_without_a_cj_mapping_gets_na_as_its_id(self, broker):
        broker.api.trades = [sj_trade(sj_id="unmapped")]
        assert broker.list_orders()[0].id == "N/A"

    def test_missing_optional_fields_default_to_na(self, broker):
        sparse = NS(order=NS(quantity=1, price=10.0),
                    status=NS(id="sj1", status=Status.Inactive))
        broker.api.trades = [sparse]
        (t,) = broker.list_orders()
        assert t.symbol == "N/A"
        assert (t.action, t.order_type, t.price_type, t.order_lot) == ("N/A",) * 4
        assert (t.order_datetime, t.ordno, t.deals) == ("N/A", "N/A", 0)
        assert t.status == "UNKNOWN"

    def test_an_sdk_error_gives_an_empty_list(self, broker):
        broker.api.fail["list_trades"] = RuntimeError("timeout")
        assert broker.list_orders() == []


class TestBuySellStock:
    """The convenience wrappers build a TSE LMT ROD order and place it."""

    def sent_order(self, broker):
        return next(c[1][1] for c in broker.api.calls if c[0] == "place_order")

    def test_buy_stock_places_an_intraday_odd_limit_buy(self, broker):
        broker.api.next_trade = sj_trade()
        broker.buy_stock("2330", quantity=5, price=480.0)
        sj_order = self.sent_order(broker)
        assert sj_order.action == sj.constant.Action.Buy
        assert (sj_order.quantity, sj_order.price) == (5, 480.0)
        assert sj_order.price_type == sj.constant.StockPriceType.LMT
        assert sj_order.order_type == sj.constant.OrderType.ROD
        assert sj_order.order_lot == sj.constant.StockOrderLot.IntradayOdd

    def test_sell_stock_places_a_limit_sell(self, broker):
        broker.api.next_trade = sj_trade()
        broker.sell_stock("2330", quantity=5, price=520.0)
        sj_order = self.sent_order(broker)
        assert sj_order.action == sj.constant.Action.Sell
        assert sj_order.price == 520.0

    @pytest.mark.parametrize("method", ["buy_stock", "sell_stock"])
    def test_intraday_odd_false_sends_a_common_lot(self, broker, method):
        broker.api.next_trade = sj_trade()
        getattr(broker, method)("2330", quantity=1, price=500.0, intraday_odd=False)
        assert self.sent_order(broker).order_lot == sj.constant.StockOrderLot.Common

    @pytest.mark.parametrize("method", ["buy_stock", "sell_stock"])
    def test_the_wrapper_refreshes_state_after_placing(self, broker, method):
        broker.api.next_trade = sj_trade()
        result = getattr(broker, method)("2330", quantity=1, price=500.0)
        assert isinstance(result, OrderResult)
        names = broker.api.names()
        assert names.index("place_order") < names.index("update_status")


# ── Order callbacks ───────────────────────────────────────────────────────────

class TestRegisterOrderCallback:
    def test_the_shioaji_callback_is_installed_once(self, broker):
        broker.register_order_callback(lambda e: None)
        broker.register_order_callback(lambda e: None)
        assert broker.api.names().count("set_order_callback") == 1
        assert len(broker._order_callbacks) == 2


class TestShioajiOrderCallback:
    """The installed shioaji callback turns order/deal pushes into OrderEvents."""

    @pytest.fixture
    def wired(self, broker):
        events = []
        broker.register_order_callback(events.append)
        trade = sj_trade(sj_id="sj1", seqno="000777")
        cj_sj_order_map["cj1"] = trade
        insert_new_ordermap_item_to_db(conn=broker.db, cj_order_id="cj1",
                                       bkr_order_id="sj1", broker="sinopac")
        insert_new_order_to_db(conn=broker.db, username="u", order=make_order(id="cj1"))
        return broker, events

    @staticmethod
    def order_msg(op_type="New", sj_id="sj1", action="Buy", status=None):
        msg = {"operation": {"op_type": op_type, "op_code": "00"},
               "order": {"id": sj_id, "action": action, "quantity": 3, "price": 500.0},
               "contract": {"code": "2330"}}
        if status is not None:
            msg["status"] = status
        return msg

    @staticmethod
    def deal_msg(seqno="000777", action="Buy"):
        return {"seqno": seqno, "code": "2330", "action": action, "quantity": 2,
                "price": 501.0, "trade_id": "T42"}

    def fire(self, broker, stat, msg):
        broker.api.order_callback(stat, msg)

    def test_a_new_order_push_emits_a_committed_event(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg("New"))
        (e,) = events
        assert e.event_type == EventType.ORDER_STATUS_CHANGE
        assert (e.order_id, e.symbol, e.action, e.quantity, e.price) == \
            ("cj1", "2330", OrderAction.BUY, 3, 500.0)
        assert e.old_status == OrderStatus.PLACED
        assert e.new_status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert (e.filled_quantity, e.filled_price, e.filled_value) == (0, None, None)
        assert e.broker_raw_data["sj_order_id"] == "sj1"
        assert e.broker_raw_data["op_type"] == "New"

    @pytest.mark.parametrize("op_type, cj_status", [
        ("Cancel", OrderStatus.CANCELLED),
        ("Failed", OrderStatus.REJECTED),
        ("UpdateQty", OrderStatus.COMMITTED_WAIT_MATCHING),
        ("UpdatePrice", OrderStatus.COMMITTED_WAIT_MATCHING),
        ("Something", OrderStatus.UNKNOWN),
    ])
    def test_the_operation_type_sets_the_new_status_and_the_db(self, wired, op_type, cj_status):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg(op_type))
        assert events[0].new_status == cj_status
        assert order_status_in_db(broker.db, "cj1") == cj_status.value

    def test_the_previous_event_status_becomes_the_next_old_status(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg("New"))
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg("Cancel"))
        assert events[1].old_status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert events[1].new_status == OrderStatus.CANCELLED

    @pytest.mark.parametrize("action, cj_action", [("Sell", OrderAction.SELL), ("Hold", None)])
    def test_the_action_string_is_mapped_to_a_cj_action(self, wired, action, cj_action):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg(action=action))
        assert events[0].action == cj_action

    def test_deal_figures_in_an_order_push_give_the_filled_value(self, wired):
        broker, events = wired
        msg = self.order_msg("New", status={"deal_quantity": 2, "deal_price": 499.5})
        self.fire(broker, sj.constant.OrderState.StockOrder, msg)
        assert (events[0].filled_quantity, events[0].filled_price) == (2, 499.5)
        assert events[0].filled_value == 999.0

    def test_a_deal_push_is_matched_by_seqno_and_reported_filled(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockDeal, self.deal_msg())
        (e,) = events
        assert e.order_id == "cj1"
        assert e.new_status == OrderStatus.FILLED
        assert (e.filled_quantity, e.filled_price, e.filled_value) == (2, 501.0, 1002.0)
        assert e.broker_raw_data["deal_id"] == "T42"
        assert e.broker_raw_data["op_type"] == "Deal"
        assert order_status_in_db(broker.db, "cj1") == "FILLED"

    def test_a_deal_for_an_uncached_order_is_matched_via_list_trades(self, wired):
        broker, events = wired
        cj_sj_order_map.clear()
        broker.api.trades = [NS(), sj_trade(sj_id="sj1", seqno="000777")]
        self.fire(broker, sj.constant.OrderState.StockDeal, self.deal_msg())
        assert [e.order_id for e in events] == ["cj1"]

    def test_a_deal_with_an_unknown_seqno_is_ignored(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockDeal, self.deal_msg(seqno="999999"))
        assert events == []
        assert order_status_in_db(broker.db, "cj1") == "PLACED"

    def test_a_push_for_an_order_cjtrade_did_not_place_is_ignored(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg(sj_id="foreign"))
        assert events == []

    def test_a_push_whose_trade_cannot_be_retrieved_is_ignored(self, wired):
        broker, events = wired
        cj_sj_order_map.clear()                 # mapped in DB, but not at the broker
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg())
        assert events == []

    def test_a_malformed_push_is_swallowed(self, wired):
        broker, events = wired
        self.fire(broker, sj.constant.OrderState.StockOrder, {"order": {}})
        assert events == []

    def test_a_failing_user_callback_does_not_stop_the_others_or_the_db_update(self, wired):
        broker, events = wired
        def bad(event):
            raise RuntimeError("user bug")
        broker._order_callbacks.insert(0, bad)
        self.fire(broker, sj.constant.OrderState.StockOrder, self.order_msg("Cancel"))
        assert len(events) == 1
        assert order_status_in_db(broker.db, "cj1") == "CANCELLED"
