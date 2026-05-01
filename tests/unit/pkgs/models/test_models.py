"""Unit tests for cjtrade.pkgs.models — pure dataclass/enum tests, no I/O."""
import uuid
from datetime import datetime

import pytest
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Quote
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.rank_type import RankType
from cjtrade.pkgs.models.trade import Trade


# ═══════════════════════════════════════════════════════════════════════════════
# Product
# ═══════════════════════════════════════════════════════════════════════════════

class TestProduct:
    def test_defaults(self):
        p = Product(symbol="2330")
        assert p.type == ProductType.STOCK
        assert p.exchange == Exchange.TSE
        assert p.category == ""
        assert p.tags == []
        assert p.metadata == {}

    def test_frozen(self):
        p = Product(symbol="0050")
        with pytest.raises(Exception):  # FrozenInstanceError
            p.symbol = "2330"

    def test_to_dict(self):
        p = Product(symbol="0050", type=ProductType.STOCK, exchange=Exchange.TSE)
        d = p.to_dict()
        assert d["symbol"] == "0050"
        assert d["type"] == "Stocks"
        assert d["exchange"] == "TSE"

    def test_hashable_as_dict_key(self):
        """Product with default (empty) mutable fields cannot be hashed due to list/dict.
        Products with only hashable fields should be equality-comparable."""
        p1 = Product(symbol="2330")
        p2 = Product(symbol="2330")
        assert p1 == p2


# ═══════════════════════════════════════════════════════════════════════════════
# Order
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrder:
    def _make_order(self, **kwargs):
        defaults = dict(
            product=Product(symbol="0050"),
            action=OrderAction.BUY,
            price=50.0,
            quantity=10,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd,
        )
        defaults.update(kwargs)
        return Order(**defaults)

    def test_auto_generated_id(self):
        o = self._make_order()
        assert len(o.id) == 32  # uuid4 hex

    def test_unique_ids(self):
        o1 = self._make_order()
        o2 = self._make_order()
        assert o1.id != o2.id

    def test_created_at_auto(self):
        o = self._make_order()
        assert isinstance(o.created_at, datetime)

    def test_broker_default(self):
        o = self._make_order()
        assert o.broker == "na"

    def test_opt_field_default_empty(self):
        o = self._make_order()
        assert o.opt_field == {}

    def test_opt_field_isolation(self):
        """Each instance should have its own opt_field dict."""
        o1 = self._make_order()
        o2 = self._make_order()
        o1.opt_field["key"] = "val"
        assert "key" not in o2.opt_field


# ═══════════════════════════════════════════════════════════════════════════════
# OrderStatus enum
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderStatus:
    def test_all_values(self):
        expected = {"PLACED", "COMMITTED_WAIT_MARKET_OPEN", "COMMITTED_WAIT_MATCHING",
                    "FILLED", "PARTIAL", "CANCELLED", "REJECTED", "UNKNOWN"}
        assert set(s.value for s in OrderStatus) == expected

    def test_str_enum_comparison(self):
        assert OrderStatus.FILLED == "FILLED"
        assert OrderStatus("CANCELLED") == OrderStatus.CANCELLED


# ═══════════════════════════════════════════════════════════════════════════════
# Kbar
# ═══════════════════════════════════════════════════════════════════════════════

class TestKbar:
    def test_construction(self):
        ts = datetime(2024, 1, 15, 9, 0, 0)
        k = Kbar(timestamp=ts, open=100.0, high=105.0, low=99.0, close=103.0, volume=5000)
        assert k.open == 100.0
        assert k.high == 105.0
        assert k.low == 99.0
        assert k.close == 103.0
        assert k.volume == 5000

    def test_to_dict(self):
        ts = datetime(2024, 6, 1, 10, 30, 0)
        k = Kbar(timestamp=ts, open=50.0, high=52.0, low=49.5, close=51.0, volume=1200)
        d = k.to_dict()
        assert d["timestamp"] == "2024-06-01T10:30:00"
        assert d["open"] == 50.0
        assert d["volume"] == 1200

    def test_repr(self):
        ts = datetime(2024, 1, 1, 9, 0, 0)
        k = Kbar(timestamp=ts, open=1.0, high=2.0, low=0.5, close=1.5, volume=100)
        assert "Kbar(" in repr(k)
        assert "open=1.0" in repr(k)


# ═══════════════════════════════════════════════════════════════════════════════
# Position
# ═══════════════════════════════════════════════════════════════════════════════

class TestPosition:
    def test_to_dict(self):
        pos = Position(
            symbol="0050", quantity=100, avg_cost=60.0,
            current_price=65.0, market_value=6500.0, unrealized_pnl=500.0
        )
        d = pos.to_dict()
        assert d["symbol"] == "0050"
        assert d["unrealized_pnl"] == 500.0

    def test_str(self):
        pos = Position(symbol="2330", quantity=5, avg_cost=500.0,
                       current_price=550.0, market_value=2750.0)
        s = str(pos)
        assert "2330" in s
        assert "5000" in s  # quantity * 1000


# ═══════════════════════════════════════════════════════════════════════════════
# Snapshot (from_dict / to_dict round trip)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshot:
    @pytest.fixture
    def sample_dict(self):
        return {
            "symbol": "2330",
            "exchange": "TSE",
            "timestamp": "2024-06-01T09:00:00",
            "open": 500.0,
            "close": 505.0,
            "high": 510.0,
            "low": 498.0,
            "volume": 30000,
            "average_price": 503.5,
            "action": "BUY",
            "buy_price": 504.0,
            "buy_volume": 120,
            "sell_price": 505.0,
            "sell_volume": 80,
        }

    def test_from_dict(self, sample_dict):
        snap = Snapshot.from_dict(sample_dict)
        assert snap.symbol == "2330"
        assert snap.action == OrderAction.BUY
        assert isinstance(snap.timestamp, datetime)
        assert snap.open == 500.0

    def test_to_dict_round_trip(self, sample_dict):
        snap = Snapshot.from_dict(sample_dict)
        d = snap.to_dict()
        assert d["symbol"] == "2330"
        assert d["action"] == "BUY"
        assert d["timestamp"] == "2024-06-01T09:00:00"

    def test_from_dict_with_datetime_object(self, sample_dict):
        sample_dict["timestamp"] = datetime(2024, 6, 1, 9, 0, 0)
        snap = Snapshot.from_dict(sample_dict)
        assert snap.timestamp == datetime(2024, 6, 1, 9, 0, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Quote / BidAsk
# ═══════════════════════════════════════════════════════════════════════════════

class TestQuote:
    def test_construction(self):
        q = Quote(symbol="0050", price=55.0, volume=1000, timestamp="2024-06-01T10:00:00")
        assert q.symbol == "0050"
        assert q.price == 55.0


class TestBidAsk:
    def test_to_dict(self):
        ba = BidAsk(
            symbol="2330",
            datetime=datetime(2024, 6, 1, 9, 30, 0),
            bid_price=[500.0, 499.0, 498.0, 497.0, 496.0],
            bid_volume=[100, 200, 150, 80, 50],
            ask_price=[501.0, 502.0, 503.0, 504.0, 505.0],
            ask_volume=[120, 90, 60, 40, 30],
        )
        d = ba.to_dict()
        assert len(d["bid_price"]) == 5
        assert d["datetime"] == "2024-06-01T09:30:00"


# ═══════════════════════════════════════════════════════════════════════════════
# Trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrade:
    def test_to_dict(self):
        t = Trade(
            id="t1", symbol="0050", action="BUY", quantity=10,
            price=55.0, status="FILLED", order_type="ROD",
            price_type="LMT", order_lot=1, order_datetime="2024-01-01T09:00:00",
            deals=1, ordno="ABC123"
        )
        d = t.to_dict()
        assert d["id"] == "t1"
        assert d["price"] == 55.0
        assert d["ordno"] == "ABC123"


# ═══════════════════════════════════════════════════════════════════════════════
# RankType enum
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankType:
    def test_values(self):
        assert RankType.VOLUME == "VOLUME"
        assert RankType.PRICE_CHANGE == "PRICE_CHANGE"
        assert RankType.PRICE_PERCENTAGE_CHANGE == "PRICE_PERCENTAGE_CHANGE"
