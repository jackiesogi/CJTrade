"""Unit tests for the CJTrade <-> shioaji conversions in sinopac/_internal_func.py.

Only shioaji's constant enums and its plain `sj.Order` model are used; both
build without a session. Contracts, trades and quotes are SimpleNamespace
fakes carrying just the attributes the converters read.
"""
import types
from datetime import datetime
from decimal import Decimal

import pytest
import shioaji as sj
from cjtrade.pkgs.brokers.sinopac import _internal_func as internal
from cjtrade.pkgs.brokers.sinopac._internal_func import _aggregate_by_time_windows
from cjtrade.pkgs.brokers.sinopac._internal_func import _aggregate_by_trading_session
from cjtrade.pkgs.brokers.sinopac._internal_func import _aggregate_daily_to_monthly
from cjtrade.pkgs.brokers.sinopac._internal_func import _aggregate_daily_to_weekly
from cjtrade.pkgs.brokers.sinopac._internal_func import _aggregate_kbars
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_bidask
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_kbar
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_order
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_product
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_result
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_snapshot
from cjtrade.pkgs.brokers.sinopac._internal_func import _retrieve_sinopac_trade_by_cj_order_id
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_order
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_product
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_ranktype
from cjtrade.pkgs.brokers.sinopac._internal_func import cj_sj_order_map
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import insert_new_ordermap_item_to_db
from cjtrade.pkgs.db.db_api import prepare_cjtrade_tables
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType
from cjtrade.pkgs.models.rank_type import RankType

NS = types.SimpleNamespace


@pytest.fixture(autouse=True)
def empty_order_map():
    # cj_sj_order_map is module state shared with the broker adapter.
    cj_sj_order_map.clear()
    yield
    cj_sj_order_map.clear()


@pytest.fixture
def tmp_db(tmp_path):
    conn = connect_sqlite(database=str(tmp_path / "mirror.db"))
    prepare_cjtrade_tables(conn)
    yield conn
    conn.close()


def make_order(action=OrderAction.BUY, price_type=PriceType.LMT,
               order_type=OrderType.ROD, order_lot=OrderLot.IntraDayOdd,
               price=500.0, quantity=3):
    return Order(
        product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol="2330"),
        action=action, price=price, quantity=quantity,
        price_type=price_type, order_type=order_type, order_lot=order_lot,
    )


def bar(ts, o=10.0, h=11.0, l=9.0, c=10.5, v=100, symbol="2330"):
    return Kbar(timestamp=ts, open=o, high=h, low=l, close=c, volume=v, symbol=symbol)


class TestToSinopacOrder:
    """CJ Order -> sj.Order carries side, price type, time in force and lot."""

    @pytest.mark.parametrize("cj_action, sj_action", [
        (OrderAction.BUY, sj.constant.Action.Buy),
        (OrderAction.SELL, sj.constant.Action.Sell),
    ])
    def test_the_side_is_mapped_to_the_matching_shioaji_action(self, cj_action, sj_action):
        assert _to_sinopac_order(None, make_order(action=cj_action)).action == sj_action

    @pytest.mark.parametrize("cj_type, sj_type", [
        (PriceType.LMT, sj.constant.StockPriceType.LMT),
        (PriceType.MKT, sj.constant.StockPriceType.MKT),
    ])
    def test_the_price_type_is_mapped(self, cj_type, sj_type):
        assert _to_sinopac_order(None, make_order(price_type=cj_type)).price_type == sj_type

    @pytest.mark.parametrize("cj_type, sj_type", [
        (OrderType.ROD, sj.constant.OrderType.ROD),
        (OrderType.IOC, sj.constant.OrderType.IOC),
        (OrderType.FOK, sj.constant.OrderType.FOK),
    ])
    def test_the_order_type_is_mapped(self, cj_type, sj_type):
        assert _to_sinopac_order(None, make_order(order_type=cj_type)).order_type == sj_type

    @pytest.mark.parametrize("cj_lot, sj_lot", [
        (OrderLot.IntraDayOdd, sj.constant.StockOrderLot.IntradayOdd),
        (OrderLot.Common, sj.constant.StockOrderLot.Common),
    ])
    def test_the_order_lot_is_mapped(self, cj_lot, sj_lot):
        assert _to_sinopac_order(None, make_order(order_lot=cj_lot)).order_lot == sj_lot

    def test_price_and_quantity_are_passed_through(self):
        sj_order = _to_sinopac_order(None, make_order(price=31.65, quantity=7))
        assert sj_order.price == 31.65
        assert sj_order.quantity == 7

    def test_a_gtc_order_is_rejected_as_an_unsupported_field(self):
        with pytest.raises(ValueError, match="Unsupported order field"):
            _to_sinopac_order(None, make_order(order_type=OrderType.GTC))

    def test_a_cancel_action_is_rejected_as_an_unsupported_field(self):
        with pytest.raises(ValueError, match="Unsupported order field"):
            _to_sinopac_order(None, make_order(action=OrderAction.CANCEL))


class TestFromSinopacOrder:
    """sj.Order + contract -> CJ Order is the inverse of _to_sinopac_order."""

    @pytest.mark.parametrize("action", [OrderAction.BUY, OrderAction.SELL])
    @pytest.mark.parametrize("price_type", [PriceType.LMT, PriceType.MKT])
    @pytest.mark.parametrize("order_type", [OrderType.ROD, OrderType.IOC, OrderType.FOK])
    @pytest.mark.parametrize("order_lot", [OrderLot.IntraDayOdd, OrderLot.Common])
    def test_a_round_trip_preserves_every_mapped_field(self, action, price_type, order_type, order_lot):
        original = make_order(action=action, price_type=price_type,
                              order_type=order_type, order_lot=order_lot)
        contract = NS(code="2330", exchange=sj.constant.Exchange.TSE)
        back = _from_sinopac_order(_to_sinopac_order(None, original), contract)
        assert (back.action, back.price_type, back.order_type, back.order_lot) == \
            (action, price_type, order_type, order_lot)
        assert back.price == original.price
        assert back.quantity == original.quantity
        assert back.product.symbol == "2330"
        assert back.broker == "sinopac"

    def test_an_unknown_shioaji_field_value_raises_value_error(self):
        sj_order = NS(action="Hold", price_type=sj.constant.StockPriceType.LMT,
                      order_type=sj.constant.OrderType.ROD,
                      order_lot=sj.constant.StockOrderLot.Common, price=1.0, quantity=1)
        with pytest.raises(ValueError, match="Unsupported Shioaji order field"):
            _from_sinopac_order(sj_order, NS(code="2330"))


class TestFromSinopacProduct:
    """Shioaji contracts become STOCK products, falling back to TSE."""

    def test_a_tse_stock_contract_maps_to_a_tse_stock_product(self):
        contract = NS(security_type=NS(value="STK"), exchange=sj.constant.Exchange.TSE, code="2330")
        product = _from_sinopac_product(contract)
        assert product == Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol="2330")

    def test_string_security_type_and_exchange_are_accepted(self):
        product = _from_sinopac_product(NS(security_type="FUT", exchange="TSE", code="0050"))
        assert product.type == ProductType.STOCK          # non-STK falls back to STOCK
        assert product.exchange == Exchange.TSE

    def test_an_unknown_exchange_falls_back_to_tse(self):
        assert _from_sinopac_product(NS(exchange="XYZ", code="1")).exchange == Exchange.TSE

    def test_a_bare_contract_gets_stock_and_tse_defaults(self):
        product = _from_sinopac_product(NS(code="2890"))
        assert (product.type, product.exchange, product.symbol) == \
            (ProductType.STOCK, Exchange.TSE, "2890")

    def test_symbol_is_used_when_the_contract_has_no_code(self):
        assert _from_sinopac_product(NS(symbol="TSE2330")).symbol == "TSE2330"

    def test_a_contract_with_neither_code_nor_symbol_gets_an_empty_symbol(self):
        assert _from_sinopac_product(NS()).symbol == ""


class TestToSinopacProduct:
    """CJ Product -> contract is a lookup in api.Contracts.<type>[symbol]."""

    def test_the_contract_is_looked_up_by_product_type_and_symbol(self):
        contract = NS(code="2330")
        api = NS(Contracts=NS(Stocks={"2330": contract}))
        assert _to_sinopac_product(api, Product(symbol="2330")) is contract

    def test_an_unknown_symbol_raises_value_error(self):
        api = NS(Contracts=NS(Stocks={}))
        with pytest.raises(ValueError, match="Cannot resolve Sinopac contract"):
            _to_sinopac_product(api, Product(symbol="9999"))

    def test_an_api_without_that_contract_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot resolve Sinopac contract"):
            _to_sinopac_product(NS(Contracts=NS()), Product(symbol="2330"))


class TestToSinopacRanktype:
    @pytest.mark.parametrize("rank, scanner", [
        (RankType.PRICE_PERCENTAGE_CHANGE, sj.constant.ScannerType.ChangePercentRank),
        (RankType.PRICE_CHANGE, sj.constant.ScannerType.ChangePriceRank),
        (RankType.VOLUME, sj.constant.ScannerType.VolumeRank),
    ])
    def test_each_rank_type_maps_to_its_scanner(self, rank, scanner):
        assert _to_sinopac_ranktype(rank) == scanner

    def test_an_unknown_rank_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported rank type"):
            _to_sinopac_ranktype("AMOUNT")


class TestFromSinopacResult:
    """Trade status -> OrderResult; missing data becomes UNKNOWN, never an exception."""

    @pytest.mark.parametrize("sj_status, cj_status", [
        (sj.constant.Status.PendingSubmit, OrderStatus.PLACED),
        (sj.constant.Status.PreSubmitted, OrderStatus.COMMITTED_WAIT_MARKET_OPEN),
        (sj.constant.Status.Submitted, OrderStatus.COMMITTED_WAIT_MATCHING),
        (sj.constant.Status.Filled, OrderStatus.FILLED),
        (sj.constant.Status.PartFilled, OrderStatus.PARTIAL),
        (sj.constant.Status.Cancelled, OrderStatus.CANCELLED),
        (sj.constant.Status.Failed, OrderStatus.REJECTED),
        (sj.constant.Status.Inactive, OrderStatus.UNKNOWN),   # not in STATUS_MAP
    ])
    def test_each_shioaji_status_maps_to_its_cj_status(self, sj_status, cj_status):
        trade = NS(status=NS(status=sj_status, id="sj1", deals=[]))
        assert _from_sinopac_result(trade).status == cj_status

    def test_the_result_links_to_the_shioaji_order_id_and_keeps_the_deals(self):
        deals = [NS(price=10.0, quantity=1)]
        status = NS(status=sj.constant.Status.PartFilled, id="abc123", deals=deals)
        result = _from_sinopac_result(NS(status=status))
        assert result.linked_order == "abc123"
        assert result.metadata["broker"] == "sinopac"
        assert result.metadata["deals"] == deals
        assert result.metadata["raw_status"] is status

    def test_a_status_without_id_or_deals_gets_empty_defaults(self):
        result = _from_sinopac_result(NS(status=NS(status=sj.constant.Status.Submitted)))
        assert result.linked_order == ""
        assert result.metadata["deals"] == []

    def test_a_none_result_is_unknown_with_a_null_result_error(self):
        result = _from_sinopac_result(None)
        assert result.status == OrderStatus.UNKNOWN
        assert result.metadata["error"] == "null_result"
        assert result.metadata["raw_result"] is None
        assert result.linked_order == ""

    @pytest.mark.parametrize("sj_result", [NS(), NS(status=None)])
    def test_a_result_without_status_is_unknown_with_a_no_status_error(self, sj_result):
        result = _from_sinopac_result(sj_result)
        assert result.status == OrderStatus.UNKNOWN
        assert result.metadata["error"] == "no_status"
        assert result.metadata["raw_result"] == str(sj_result)


class TestFromSinopacSnapshot:
    """Snapshot conversion reads every field with a default and shifts ts by 8h."""

    def full_snapshot(self, **overrides):
        fields = dict(
            ts=1_705_291_200_000_000_000, code="2330", exchange="TSE",
            open=600.0, close=605.0, high=610.0, low=598.0, volume=12345,
            average_price=603.2, tick_type=sj.constant.TickType.Buy,
            buy_price=604.0, buy_volume=10, sell_price=605.0, sell_volume=20,
        )
        fields.update(overrides)
        return NS(**fields)

    def test_all_price_and_volume_fields_are_copied(self):
        snap = _from_sinopac_snapshot(self.full_snapshot())
        assert (snap.symbol, snap.exchange) == ("2330", "TSE")
        assert (snap.open, snap.close, snap.high, snap.low) == (600.0, 605.0, 610.0, 598.0)
        assert snap.volume == 12345
        assert snap.average_price == 603.2
        assert (snap.buy_price, snap.buy_volume, snap.sell_price, snap.sell_volume) == \
            (604.0, 10, 605.0, 20)

    def test_the_timestamp_has_eight_hours_subtracted(self):
        raw = 1_705_291_200_000_000_000
        snap = _from_sinopac_snapshot(self.full_snapshot(ts=raw))
        assert snap.timestamp == datetime.fromtimestamp(raw / 1_000_000_000 - 8 * 3600)

    @pytest.mark.parametrize("tick_type, action", [
        (sj.constant.TickType.Buy, OrderAction.BUY),
        (sj.constant.TickType.Sell, OrderAction.SELL),
        (sj.constant.TickType.No, "N/A"),
    ])
    def test_the_tick_type_becomes_the_snapshot_action(self, tick_type, action):
        assert _from_sinopac_snapshot(self.full_snapshot(tick_type=tick_type)).action == action

    def test_a_missing_timestamp_falls_back_to_now(self):
        before = datetime.now()
        snap = _from_sinopac_snapshot(NS(code="2330"))
        assert before <= snap.timestamp <= datetime.now()

    def test_missing_fields_get_zero_or_na_defaults(self):
        snap = _from_sinopac_snapshot(NS(symbol="0050"))
        assert snap.symbol == "0050"
        assert snap.exchange == "N/A"
        assert (snap.open, snap.close, snap.volume) == (0.0, 0.0, 0)
        assert snap.action == "N/A"

    def test_an_unusable_timestamp_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot convert Shioaji snapshot"):
            _from_sinopac_snapshot(NS(ts="not-a-number"))


class TestFromSinopacKbarSymbol:
    def test_every_bar_carries_the_callers_symbol(self):
        raw = NS(ts=[0, 60_000_000_000], Open=[1, 2], High=[1, 2], Low=[1, 2],
                 Close=[1, 2], Volume=[5, 6])
        assert [k.symbol for k in _from_sinopac_kbar(raw, "2330")] == ["2330", "2330"]

    def test_an_empty_response_gives_no_bars(self):
        raw = NS(ts=[], Open=[], High=[], Low=[], Close=[], Volume=[])
        assert _from_sinopac_kbar(raw, "2330") == []


class TestFromSinopacBidask:
    def test_prices_become_floats_and_volumes_lists(self):
        dt = datetime(2026, 1, 5, 10, 0)
        raw = NS(code="2330", datetime=dt,
                 bid_price=(Decimal("600.5"), Decimal("600")), bid_volume=(3, 4),
                 ask_price=(Decimal("601"),), ask_volume=(9,))
        book = _from_sinopac_bidask(raw)
        assert (book.symbol, book.datetime) == ("2330", dt)
        assert book.bid_price == [600.5, 600.0]
        assert all(type(p) is float for p in book.bid_price + book.ask_price)
        assert book.bid_volume == [3, 4]
        assert book.ask_price == [601.0]
        assert book.ask_volume == [9]


class TestRetrieveSinopacTradeByCjOrderId:
    """Lookup order: in-memory map, then DB id -> api.list_trades()."""

    class Api:
        def __init__(self, trades):
            self.trades = trades
            self.calls = 0

        def list_trades(self):
            self.calls += 1
            return self.trades

    def test_a_cached_trade_is_returned_without_asking_the_api(self, tmp_db):
        trade = NS(status=NS(id="sj1"))
        cj_sj_order_map["cj1"] = trade
        api = self.Api([])
        assert _retrieve_sinopac_trade_by_cj_order_id(api, tmp_db, "cj1") is trade
        assert api.calls == 0

    def test_a_trade_found_via_the_db_mapping_is_returned_and_cached(self, tmp_db):
        insert_new_ordermap_item_to_db(conn=tmp_db, cj_order_id="cj1",
                                       bkr_order_id="sj1", broker="sinopac")
        wanted = NS(status=NS(id="sj1"))
        api = self.Api([NS(), NS(status=NS(id="other")), wanted])  # first lacks status
        assert _retrieve_sinopac_trade_by_cj_order_id(api, tmp_db, "cj1") is wanted
        assert cj_sj_order_map["cj1"] is wanted

    def test_an_unmapped_id_returns_none_without_asking_the_api(self, tmp_db):
        api = self.Api([NS(status=NS(id="sj1"))])
        assert _retrieve_sinopac_trade_by_cj_order_id(api, tmp_db, "nope") is None
        assert api.calls == 0

    def test_a_mapped_id_missing_from_the_broker_returns_none(self, tmp_db):
        insert_new_ordermap_item_to_db(conn=tmp_db, cj_order_id="cj1",
                                       bkr_order_id="sj1", broker="sinopac")
        api = self.Api([NS(status=NS(id="other"))])
        assert _retrieve_sinopac_trade_by_cj_order_id(api, tmp_db, "cj1") is None
        assert "cj1" not in cj_sj_order_map


class TestAggregateKbars:
    """1-minute bars are rolled up into intraday windows or trading sessions."""

    def test_no_bars_give_no_bars(self):
        assert _aggregate_kbars([], "5m") == []

    def test_an_unsupported_interval_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported interval"):
            _aggregate_kbars([bar(datetime(2026, 1, 5, 9, 1))], "7m")

    def test_one_minute_bars_are_returned_unchanged(self):
        bars = [bar(datetime(2026, 1, 5, 9, 1))]
        assert _aggregate_kbars(bars, "1m") is bars

    def test_five_minute_windows_take_first_open_max_high_min_low_last_close_sum_volume(self):
        bars = [
            bar(datetime(2026, 1, 5, 9, 0), o=10, h=11, l=9.5, c=10.2, v=1),
            bar(datetime(2026, 1, 5, 9, 2), o=10.2, h=12, l=10, c=11.1, v=2),
            bar(datetime(2026, 1, 5, 9, 4), o=11.1, h=11.5, l=9, c=9.876, v=3),
            bar(datetime(2026, 1, 5, 9, 5), o=20, h=21, l=19, c=20.5, v=4),
        ]
        out = _aggregate_kbars(bars, "5m")
        assert [k.timestamp for k in out] == [datetime(2026, 1, 5, 9, 0), datetime(2026, 1, 5, 9, 5)]
        first = out[0]
        assert (first.open, first.high, first.low, first.close, first.volume) == (10, 12, 9, 9.88, 6)
        assert type(first.volume) is int
        assert {k.symbol for k in out} == {"2330"}

    def test_empty_intraday_windows_are_dropped(self):
        bars = [bar(datetime(2026, 1, 5, 9, 0)), bar(datetime(2026, 1, 5, 9, 20))]
        out = _aggregate_kbars(bars, "5m")
        assert [k.timestamp.minute for k in out] == [0, 20]

    def test_daily_bars_are_one_per_trading_day_stamped_at_nine(self):
        bars = [
            bar(datetime(2026, 1, 6, 13, 30), o=8, h=8, l=7, c=7.5, v=5),
            bar(datetime(2026, 1, 5, 9, 1), o=10, h=11, l=9, c=10, v=1),
            bar(datetime(2026, 1, 5, 13, 30), o=10, h=12, l=8, c=11, v=2),   # day's close
            bar(datetime(2026, 1, 6, 9, 1), o=9, h=9.5, l=6, c=8, v=4),
        ]
        out = _aggregate_kbars(bars, "1d")
        assert [k.timestamp for k in out] == [datetime(2026, 1, 5, 9, 0), datetime(2026, 1, 6, 9, 0)]
        day1, day2 = out
        assert (day1.open, day1.high, day1.low, day1.close, day1.volume) == (10, 12, 8, 11, 3)
        assert (day2.open, day2.high, day2.low, day2.close, day2.volume) == (9, 9.5, 6, 7.5, 9)

    def test_weekly_bars_group_days_by_iso_week(self):
        # Fri 2026-01-02 is ISO week 1; Mon 2026-01-05 and Tue 01-06 are week 2.
        bars = [
            bar(datetime(2026, 1, 2, 10, 0), o=1, h=2, l=0.5, c=1.5, v=1),
            bar(datetime(2026, 1, 5, 10, 0), o=3, h=5, l=2, c=4, v=2),
            bar(datetime(2026, 1, 6, 10, 0), o=4, h=6, l=1, c=5, v=3),
        ]
        out = _aggregate_kbars(bars, "1w")
        assert len(out) == 2
        week2 = out[1]
        assert week2.timestamp == datetime(2026, 1, 5, 9, 0)
        assert (week2.open, week2.high, week2.low, week2.close, week2.volume) == (3, 6, 1, 5, 5)

    def test_monthly_bars_group_days_by_calendar_month(self):
        bars = [
            bar(datetime(2026, 1, 30, 10, 0), o=1, h=2, l=1, c=2, v=1),
            bar(datetime(2026, 2, 2, 10, 0), o=3, h=4, l=2, c=3, v=2),
            bar(datetime(2026, 2, 27, 10, 0), o=3, h=9, l=3, c=8, v=3),
        ]
        out = _aggregate_kbars(bars, "1M")
        assert [k.timestamp for k in out] == [datetime(2026, 1, 30, 9, 0), datetime(2026, 2, 2, 9, 0)]
        feb = out[1]
        assert (feb.open, feb.high, feb.low, feb.close, feb.volume) == (3, 9, 2, 8, 5)

    def test_an_unknown_session_interval_falls_back_to_daily(self):
        bars = [bar(datetime(2026, 1, 5, 10, 0)), bar(datetime(2026, 1, 6, 10, 0))]
        assert len(_aggregate_by_trading_session(bars, "2d")) == 2

    @pytest.mark.parametrize("fn", [
        lambda: _aggregate_by_trading_session([], "1d"),
        lambda: _aggregate_daily_to_weekly([]),
        lambda: _aggregate_daily_to_monthly([]),
        lambda: _aggregate_by_time_windows([], 5),
    ])
    def test_every_aggregation_helper_returns_empty_for_no_bars(self, fn):
        assert fn() == []


class TestMappingTables:
    """Guard the hand-written maps against silent edits."""

    def test_the_callback_operation_map_covers_shioaji_op_types(self):
        assert internal.OPERATION_TYPE_MAP == {
            'New': OrderStatus.COMMITTED_WAIT_MATCHING,
            'Cancel': OrderStatus.CANCELLED,
            'Deal': OrderStatus.FILLED,
            'UpdateQty': OrderStatus.COMMITTED_WAIT_MATCHING,
            'UpdatePrice': OrderStatus.COMMITTED_WAIT_MATCHING,
            'Failed': OrderStatus.REJECTED,
        }

    def test_the_exchange_map_only_routes_tse(self):
        assert internal.EXCHANGE_MAP == {Exchange.TSE: sj.constant.Exchange.TSE}
