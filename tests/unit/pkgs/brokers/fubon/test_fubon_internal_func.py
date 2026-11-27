"""Conversions between CJTrade models and fubon_neo objects.

The SDK's own enums and Order are used; Fubon's result objects (OrderResult,
FilledData, ...) cannot be built without a session, so they are namespaces
with the fields Fubon documents.
"""
from types import SimpleNamespace as NS

import pytest
from cjtrade.pkgs.brokers.fubon import _internal_func as fx
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product
from fubon_neo.constant import BSAction
from fubon_neo.constant import MarketType
from fubon_neo.constant import PriceType as FPriceType
from fubon_neo.constant import TimeInForce


def order(**kw):
    base = dict(product=Product("2330"), action=OrderAction.BUY, price=1000.0, quantity=1,
                price_type=PriceType.LMT, order_type=OrderType.ROD, order_lot=OrderLot.IntraDayOdd)
    base.update(kw)
    return Order(**base)


def result(**kw):
    base = dict(status=10, filled_qty=0, after_qty=1, quantity=1, market_type=MarketType.IntradayOdd,
                buy_sell=BSAction.Buy, stock_no="2330", seq_no="00000000001", order_no="bA001",
                date="2026/11/27", after_price=1000.0, price=1000.0, price_type=FPriceType.Limit,
                after_price_type=None, time_in_force=TimeInForce.ROD, last_time="10:00:00.123",
                user_def=None, error_message=None, filled_money=0)
    base.update(kw)
    return NS(**base)


class TestEnumName:
    def test_an_sdk_enum_becomes_its_member_name(self):
        assert fx.enum_name(BSAction.Buy) == "Buy"
        assert fx.enum_name(MarketType.IntradayOdd) == "IntradayOdd"

    def test_none_and_plain_strings_pass_through(self):
        assert fx.enum_name(None) == ""
        assert fx.enum_name("Sell") == "Sell"


class TestQuantity:
    def test_board_lots_are_sent_as_shares(self):
        assert fx.to_fubon_quantity(order(order_lot=OrderLot.Common, quantity=2)) == 2000

    def test_odd_lots_are_sent_as_shares_unchanged(self):
        assert fx.to_fubon_quantity(order(quantity=7)) == 7

    def test_reported_shares_come_back_in_the_orders_unit(self):
        assert fx.to_cj_quantity(result(market_type=MarketType.Common), 3000) == 3
        assert fx.to_cj_quantity(result(market_type=MarketType.IntradayOdd), 7) == 7


class TestValidation:
    def test_a_plain_odd_lot_limit_order_passes(self):
        assert fx.validate_order(order()) is None

    @pytest.mark.parametrize("kw, reason", [
        (dict(order_type=OrderType.GTC), "GTC"),
        (dict(quantity=1000), "1 to 999 shares"),
        (dict(quantity=0), "positive"),
        (dict(order_type=OrderType.IOC), "ROD only"),
        (dict(price_type=PriceType.MKT), "market orders"),
        (dict(order_lot=OrderLot.Common, quantity=500), "1 to 499 lots"),
        (dict(price=0.0), "positive price"),
        (dict(action=OrderAction.CANCEL), "unsupported action"),
    ])
    def test_orders_fubon_would_refuse_are_caught_before_sending(self, kw, reason):
        assert reason in fx.validate_order(order(**kw))

    def test_a_board_lot_market_ioc_order_passes(self):
        assert fx.validate_order(order(order_lot=OrderLot.Common, order_type=OrderType.IOC,
                                       price_type=PriceType.MKT, price=None)) is None


class TestToFubonOrder:
    def test_prices_are_sent_as_short_strings(self):
        assert fx.price_text(1000.0) == "1000"
        assert fx.price_text(66.5) == "66.5"
        assert fx.price_text(9.05) == "9.05"

    def test_the_sdk_accepts_the_built_order(self):
        text = repr(fx.to_fubon_order(order(action=OrderAction.SELL, price=66.5, quantity=3)))
        for part in ("buy_sell: Sell", 'symbol: "2330"', 'price: "66.5"', "quantity: 3",
                     "market_type: IntradayOdd", "price_type: Limit", "time_in_force: ROD",
                     "order_type: Stock"):
            assert part in text

    def test_a_board_lot_market_order_has_no_price(self):
        text = repr(fx.to_fubon_order(order(order_lot=OrderLot.Common, quantity=2,
                                            order_type=OrderType.IOC, price_type=PriceType.MKT,
                                            price=None)))
        assert "quantity: 2000" in text and "price_type: Market" in text
        assert "time_in_force: IOC" in text and "market_type: Common" in text
        assert 'price: "' not in text

    def test_the_user_def_tag_is_the_first_ten_characters_of_the_id(self):
        o = order()
        assert fx.user_def_for(o) == o.id[:10]
        assert f'user_def: "{o.id[:10]}"' in repr(fx.to_fubon_order(o))


class TestStatus:
    @pytest.mark.parametrize("code, filled, working, expected", [
        (0, 0, 1000, OrderStatus.COMMITTED_WAIT_MARKET_OPEN),
        (4, 0, 1000, OrderStatus.PLACED),
        (8, 0, 1000, OrderStatus.PLACED),
        (9, 0, 1000, OrderStatus.UNKNOWN),
        (10, 0, 1000, OrderStatus.COMMITTED_WAIT_MATCHING),
        (10, 400, 1000, OrderStatus.PARTIAL),
        (10, 1000, 1000, OrderStatus.FILLED),
        (30, 0, 0, OrderStatus.CANCELLED),
        (40, 400, 400, OrderStatus.CANCELLED),
        (50, 1000, 1000, OrderStatus.FILLED),
        (90, 0, 0, OrderStatus.REJECTED),
        (19, 0, 1000, OrderStatus.COMMITTED_WAIT_MATCHING),
        (39, 300, 1000, OrderStatus.PARTIAL),
        (77, 0, 0, OrderStatus.UNKNOWN),
    ])
    def test_fubon_status_codes_map_to_cjtrade_statuses(self, code, filled, working, expected):
        assert fx.to_cj_status(result(status=code, filled_qty=filled, after_qty=working)) == expected

    def test_a_result_with_no_status_is_unknown(self):
        assert fx.to_cj_status(NS()) == OrderStatus.UNKNOWN


class TestResultsAndTrades:
    def test_an_order_result_carries_the_cjtrade_id_and_fubons_ids(self):
        r = fx.to_cj_result(result(), cj_order_id="cj1")
        assert r.linked_order == "cj1" and r.status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert r.metadata["seq_no"] == "00000000001" and r.metadata["order_no"] == "bA001"

    def test_fubons_error_message_becomes_the_message(self):
        assert fx.to_cj_result(result(status=90, error_message="餘額不足")).message == "餘額不足"

    def test_trades_use_cjtrade_spellings_and_units(self):
        t = fx.to_cj_trade(result(market_type=MarketType.Common, after_qty=2000, buy_sell=BSAction.Sell,
                                  filled_qty=1000), "cj1")
        assert (t.action, t.quantity, t.order_lot, t.price_type, t.order_type) == \
            ("SELL", 2, "Common", "LMT", "ROD")
        assert t.status == "PARTIAL" and t.deals == 1 and t.ordno == "bA001"
        assert t.order_datetime == "2026/11/27 10:00:00.123"

    def test_an_unknown_order_gets_na_as_its_id(self):
        assert fx.to_cj_trade(result(), "").id == "N/A"


class TestAccount:
    def test_amounts_sent_as_strings_are_numbers(self):
        assert fx.to_number("666,666") == 666666.0
        assert fx.to_number(None) == 0.0 and fx.to_number("") == 0.0

    def test_positions_of_one_symbol_are_merged(self):
        rows = [NS(stock_no="2303", tradable_qty=1000, cost_price=50.0, unrealized_profit=2000,
                   unrealized_loss=0),
                NS(stock_no="2303", tradable_qty=1000, cost_price=52.0, unrealized_profit=0,
                   unrealized_loss=0),
                NS(stock_no="1101", tradable_qty=0, cost_price=40.0, unrealized_profit=0,
                   unrealized_loss=0)]
        [p] = fx.to_cj_positions(rows)
        assert (p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl) == ("2303", 2000, 51.0, 2000.0)
        assert p.market_value == 104000.0 and p.current_price == 52.0

    def test_a_loss_is_negative_pnl(self):
        [p] = fx.to_cj_positions([NS(stock_no="2330", tradable_qty=10, cost_price=1000.0,
                                     unrealized_profit=0, unrealized_loss=500)])
        assert p.unrealized_pnl == -500.0 and p.current_price == 950.0


class TestQuotes:
    QUOTE = NS(symbol="2330", market="TAIEX", open_price=1025.0, high_price=1030.0, low_price=1015.0,
               last_price=1020.0, total_volume=32029, bid_price=1020.0, bid_volume=1512,
               ask_price=1025.0, ask_volume=137)

    def test_a_symbol_quote_becomes_a_snapshot(self):
        s = fx.to_cj_snapshot(self.QUOTE)
        assert (s.symbol, s.close, s.open, s.high, s.low, s.volume) == \
            ("2330", 1020.0, 1025.0, 1030.0, 1015.0, 32029)
        assert (s.buy_price, s.sell_price) == (1020.0, 1025.0)
        assert "average_price" in s.additional_note

    def test_bid_ask_has_one_level(self):
        b = fx.to_cj_bidask(self.QUOTE)
        assert b.bid_price == [1020.0] and b.ask_volume == [137]
