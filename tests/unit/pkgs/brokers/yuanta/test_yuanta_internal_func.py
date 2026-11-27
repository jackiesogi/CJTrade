"""Conversions between CJTrade models and Yuanta Spark API objects."""
from datetime import date
from types import SimpleNamespace as NS

import pytest
from cjtrade.pkgs.brokers.yuanta import _internal_func as yx
from cjtrade.pkgs.brokers.yuanta import _spark
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product


def order(**kw):
    base = dict(product=Product("2330"), action=OrderAction.BUY, price=1000.0, quantity=1,
                price_type=PriceType.LMT, order_type=OrderType.ROD, order_lot=OrderLot.IntraDayOdd)
    base.update(kw)
    return Order(**base)


class TestHelpers:
    def test_dates_read_either_spelling_of_the_fields(self):
        assert yx.ydate(NS(ushtYear=2026, bytMon=3, bytDay=8)) == "2026/03/08"
        assert yx.ydate(NS(Year=2026, Month=11, Day=27)) == "2026/11/27"
        assert yx.ytime(NS(bytHour=9, bytMin=5, bytSec=7)) == "09:05:07"
        assert yx.ydate(None) == "" and yx.ytime(None) == ""

    def test_market_price_sentinels_are_not_prices(self):
        assert yx.num(999999999) == 0.0 and yx.num("1,234.5") == 1234.5 and yx.num("x") == 0.0

    def test_both_success_codes_are_accepted(self):
        assert yx.msg_ok(NS(MsgCode="0001")) and yx.msg_ok(NS(MsgCode="00001"))
        assert not yx.msg_ok(NS(MsgCode="0102"))

    def test_the_basket_tag_is_the_whole_cjtrade_id(self):
        o = order()
        assert yx.tag_for(o) == o.id and len(o.id) == 32


class TestValidation:
    @pytest.mark.parametrize("kw, reason", [
        (dict(order_type=OrderType.GTC), "GTC"),
        (dict(quantity=1000), "1 to 999 shares"),
        (dict(order_type=OrderType.FOK), "ROD only"),
        (dict(price_type=PriceType.MKT), "market orders"),
        (dict(order_lot=OrderLot.Common, quantity=500), "1 to 499 lots"),
        (dict(price=0.0), "positive price"),
        (dict(quantity=0), "positive"),
        (dict(action=OrderAction.CANCEL), "unsupported action"),
    ])
    def test_orders_that_would_be_refused_are_caught(self, kw, reason):
        assert reason in yx.validate_order(order(**kw))

    def test_valid_orders_pass(self):
        assert yx.validate_order(order()) is None
        assert yx.validate_order(order(order_lot=OrderLot.Common, quantity=3, price_type=PriceType.MKT,
                                       price=None, order_type=OrderType.IOC)) is None


class TestStockOrder:
    def test_a_new_order_fills_every_documented_field(self):
        o = order(action=OrderAction.SELL, price=35.15, quantity=7)
        s = yx.fill_stock_order(NS(), o, "S98875005091", 3, today=date(2026, 11, 27))
        assert vars(s) == dict(Identify=3, Account="S98875005091", OrderNo="", TradeDate="2026/11/27",
                               APCode=4, TradeKind=0, OrderType="0", StkCode="2330", BuySell="S",
                               PriceFlag=" ", Price=35.15, OrderQty=7, BasketNo=o.id, Time_in_force="0")

    def test_a_cancel_copies_the_orders_identity(self):
        row = NS(OrderNo="H00001", TradeDate=NS(ushtYear=2026, bytMon=11, bytDay=27), APCode=0,
                 OrderType="0", CompanyNo="2330", BS="B", Price=1000.0, BasketNo="abc", Time_in_Force="3")
        s = yx.fill_cancel_order(NS(), row, "S1", 9)
        assert (s.TradeKind, s.OrderNo, s.TradeDate, s.APCode, s.StkCode, s.BuySell, s.Time_in_force) == \
            (4, "H00001", "2026/11/27", 0, "2330", "B", "3")


class TestStatus:
    @pytest.mark.parametrize("code, ok, after, expected", [
        (0, 0, 1000, OrderStatus.PLACED),
        (5, 0, 1000, OrderStatus.COMMITTED_WAIT_MARKET_OPEN),
        (10, 0, 0, OrderStatus.REJECTED),
        (20, 0, 1000, OrderStatus.COMMITTED_WAIT_MATCHING),
        (20, 400, 1000, OrderStatus.PARTIAL),
        (20, 1000, 1000, OrderStatus.FILLED),
        (24, 0, 1000, OrderStatus.CANCELLED),
        (25, 300, 1000, OrderStatus.CANCELLED),
        (30, 0, 1000, OrderStatus.CANCELLED),
        (99, 0, 0, OrderStatus.UNKNOWN),
    ])
    def test_order_report_statuses(self, code, ok, after, expected):
        assert yx.to_cj_status(NS(OrderStatus=code, OkQty=ok, AfterQty=after)) == expected

    @pytest.mark.parametrize("code, expected", [
        (0, OrderStatus.COMMITTED_WAIT_MATCHING), (18, OrderStatus.COMMITTED_WAIT_MATCHING),
        (1, OrderStatus.REJECTED), (2, OrderStatus.CANCELLED), (4, OrderStatus.CANCELLED),
        (8, OrderStatus.FILLED), (24, OrderStatus.CANCELLED), (25, OrderStatus.CANCELLED),
        (3, None), (21, None), (None, None),
    ])
    def test_real_time_report_statuses(self, code, expected):
        assert yx.to_cj_status_from_report(NS(OrderStatus=code)) == expected


class TestRows:
    ROW = NS(OrderNo="H00001", TradeDate=NS(ushtYear=2026, bytMon=11, bytDay=27), CompanyNo="2330",
             BS="S", Price=1000.0, PriceFlag="2", AfterQty=3000, OkQty=1000, OrderStatus=20, APCode=0,
             Time_in_Force="0", AcceptDate=NS(ushtYear=2026, bytMon=11, bytDay=27),
             AcceptTime=NS(bytHour=9, bytMin=1, bytSec=2), ErrorMessage="", ErrorNo="")

    def test_a_report_row_becomes_a_trade_in_cjtrade_units(self):
        t = yx.to_cj_trade(self.ROW, "cj1")
        assert (t.action, t.quantity, t.order_lot, t.status, t.order_type, t.ordno) == \
            ("SELL", 3, "Common", "PARTIAL", "ROD", "H00001")
        assert t.order_datetime == "2026/11/27 09:01:02"

    def test_the_broker_key_is_date_and_order_number(self):
        assert yx.broker_key(self.ROW) == "2026/11/27:H00001"
        assert yx.broker_key(NS(OrderNo="")) is None

    def test_positions_merge_rows_of_one_symbol(self):
        rows = [NS(StkCode="2330", StockQty=1000, Price=500.0, MarketAmt=600000.0, ReturnAmt=100000.0,
                   MarketPrice=600.0),
                NS(StkCode="2330", StockQty=1000, Price=520.0, MarketAmt=600000.0, ReturnAmt=80000.0,
                   MarketPrice=600.0),
                NS(StkCode="1101", StockQty=0, Price=1.0, MarketAmt=0, ReturnAmt=0, MarketPrice=1.0)]
        [p] = yx.to_cj_positions(rows)
        assert (p.quantity, p.avg_cost, p.current_price, p.market_value, p.unrealized_pnl) == \
            (2000, 510.0, 600.0, 1200000.0, 180000.0)

    def test_a_quote_row_becomes_a_snapshot_with_market_sentinels_removed(self):
        s = yx.to_cj_snapshot(NS(StkCode="2330", OpenPrice=1.0, DealPrice=2.0, HighPrice=3.0, LowPrice=0.5,
                                 TotalVol=7, BuyPrice=999999999, SellPrice=2.1, VolFlag=0))
        assert (s.close, s.buy_price, s.sell_price, s.action) == (2.0, 0.0, 2.1, OrderAction.SELL)


class TestLoader:
    def test_a_missing_dll_is_reported_with_the_setting_to_fix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_spark, "_loaded", None)
        with pytest.raises(_spark.SparkUnavailable, match="YUANTA_DLL_DIR"):
            _spark.load(str(tmp_path))
