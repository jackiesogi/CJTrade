"""Unit tests for cjtrade.pkgs.models.event — event dataclasses and helper methods."""
from datetime import datetime

import pytest
from cjtrade.pkgs.models.event import EventType
from cjtrade.pkgs.models.event import FillEvent
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.event import PriceEvent
from cjtrade.pkgs.models.event import TickEvent
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus


class TestOrderEvent:
    @pytest.fixture
    def filled_event(self):
        return OrderEvent(
            event_type=EventType.ORDER_FILLED,
            timestamp=datetime(2024, 6, 1, 9, 30, 0),
            order_id="abc123",
            symbol="0050",
            action=OrderAction.BUY,
            quantity=10,
            price=55.0,
            old_status=OrderStatus.COMMITTED_WAIT_MATCHING,
            new_status=OrderStatus.FILLED,
            filled_quantity=10,
            filled_price=55.0,
            filled_value=550.0,
        )

    def test_is_filled(self, filled_event):
        assert filled_event.is_filled() is True
        assert filled_event.is_completely_filled() is True

    def test_is_partial(self):
        ev = OrderEvent(
            event_type=EventType.ORDER_FILLED,
            timestamp=datetime(2024, 6, 1, 9, 30, 0),
            order_id="x", symbol="0050", action=OrderAction.BUY,
            quantity=10, price=55.0,
            old_status=OrderStatus.COMMITTED_WAIT_MATCHING,
            new_status=OrderStatus.PARTIAL,
        )
        assert ev.is_filled() is True
        assert ev.is_completely_filled() is False

    def test_is_cancelled(self):
        ev = OrderEvent(
            event_type=EventType.ORDER_CANCELLED,
            timestamp=datetime(2024, 6, 1, 9, 30, 0),
            order_id="x", symbol="0050", action=OrderAction.BUY,
            quantity=10, price=55.0,
            old_status=OrderStatus.COMMITTED_WAIT_MATCHING,
            new_status=OrderStatus.CANCELLED,
        )
        assert ev.is_cancelled() is True
        assert ev.is_rejected() is False

    def test_is_rejected(self):
        ev = OrderEvent(
            event_type=EventType.ORDER_REJECTED,
            timestamp=datetime(2024, 6, 1, 9, 30, 0),
            order_id="x", symbol="0050", action=OrderAction.BUY,
            quantity=10, price=55.0,
            old_status=OrderStatus.PLACED,
            new_status=OrderStatus.REJECTED,
            message="Insufficient balance",
        )
        assert ev.is_rejected() is True
        assert ev.is_filled() is False

    def test_to_dict(self, filled_event):
        d = filled_event.to_dict()
        assert d["event_type"] == "ORDER_FILLED"
        assert d["order_id"] == "abc123"
        assert d["old_status"] == "COMMITTED_WAIT_MATCHING"
        assert d["new_status"] == "FILLED"
        assert d["filled_quantity"] == 10


class TestFillEvent:
    def test_is_complete_fill(self):
        ev = FillEvent(
            timestamp=datetime(2024, 6, 1, 10, 0, 0),
            order_id="o1", symbol="2330", action=OrderAction.BUY,
            filled_quantity=5, filled_price=500.0, filled_value=2500.0,
            total_filled_quantity=5, remaining_quantity=0,
            order_status=OrderStatus.FILLED,
        )
        assert ev.is_complete_fill() is True

    def test_partial_fill(self):
        ev = FillEvent(
            timestamp=datetime(2024, 6, 1, 10, 0, 0),
            order_id="o1", symbol="2330", action=OrderAction.BUY,
            filled_quantity=3, filled_price=500.0, filled_value=1500.0,
            total_filled_quantity=3, remaining_quantity=2,
            order_status=OrderStatus.PARTIAL,
        )
        assert ev.is_complete_fill() is False

    def test_to_dict(self):
        ev = FillEvent(
            timestamp=datetime(2024, 6, 1, 10, 0, 0),
            order_id="o1", symbol="0050", action=OrderAction.SELL,
            filled_quantity=10, filled_price=60.0, filled_value=600.0,
            total_filled_quantity=10, remaining_quantity=0,
            order_status=OrderStatus.FILLED,
            fill_sequence=2,
            deal_id="d123",
        )
        d = ev.to_dict()
        assert d["action"] == "SELL"
        assert d["fill_sequence"] == 2
        assert d["deal_id"] == "d123"


class TestPriceEvent:
    def test_to_dict(self):
        ev = PriceEvent(
            timestamp=datetime(2024, 6, 1, 10, 0, 0),
            symbol="2330", current_price=510.0, previous_price=500.0,
            condition_type="ABOVE", threshold=505.0,
            price_change=10.0, price_change_percent=2.0,
        )
        d = ev.to_dict()
        assert d["symbol"] == "2330"
        assert d["current_price"] == 510.0
        assert d["condition_type"] == "ABOVE"


class TestTickEvent:
    def test_to_dict(self):
        ev = TickEvent(
            timestamp=datetime(2024, 6, 1, 9, 0, 1),
            symbol="0050", price=55.5, volume=100,
            tick_type="BUY",
        )
        d = ev.to_dict()
        assert d["price"] == 55.5
        assert d["tick_type"] == "BUY"


class TestEventType:
    def test_all_types(self):
        expected = {"ORDER_STATUS_CHANGE", "ORDER_FILLED", "ORDER_CANCELLED",
                    "ORDER_REJECTED", "PRICE_CHANGE", "TICK"}
        assert set(e.value for e in EventType) == expected
