"""Unit tests for ArenaXMiddleWare.

Pattern demonstrated here:
  - Monkeypatch instance methods (_post / _get) to avoid real HTTP calls.
  - All tests are pure: no network, no filesystem.

To run only this file:
    pytest tests/unit/pkgs/brokers/arenax/test_middleware.py
"""
from datetime import datetime

import pytest
from cjtrade.pkgs.brokers.arenax.arenax_middleware import ArenaXMiddleWare
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


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mw():
    return ArenaXMiddleWare(host="localhost", port=8801)


@pytest.fixture
def sample_order():
    return Order(
        product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol="2330"),
        action=OrderAction.BUY,
        price=500.0,
        quantity=1,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPlaceOrderPayload:
    """Verify that place_order() serializes the Order into the correct HTTP payload."""

    def test_sends_required_fields(self, mw, sample_order):
        """The POST body must contain all fields the server expects."""
        captured = {}

        def fake_post(path, data=None, headers=None):
            captured.update(data or {})
            return {
                "ok": True,
                "result": {
                    "status": "PLACED", "message": "ok",
                    "metadata": {}, "linked_order": "", "id": sample_order.id,
                },
            }

        mw._post = fake_post
        mw.place_order(sample_order)

        assert "product" in captured
        assert "action" in captured
        assert captured["price"] == 500.0
        assert captured["quantity"] == 1
        assert captured["product"]["symbol"] == "2330"

    def test_parses_server_response_into_order_result(self, mw, sample_order):
        """A successful server response must be mapped to an OrderResult dataclass."""
        mw._post = lambda path, data=None, headers=None: {
            "ok": True,
            "result": {
                "status": "PLACED",
                "message": "accepted",
                "metadata": {"fill_price": 500.0},
                "linked_order": "abc123",
                "id": "order-id-999",
            },
        }

        result = mw.place_order(sample_order)

        assert isinstance(result, OrderResult)
        assert result.status == OrderStatus.PLACED
        assert result.message == "accepted"
        assert result.linked_order == "abc123"
        assert result.id == "order-id-999"

    def test_raises_value_error_on_server_error(self, mw, sample_order):
        """When the server returns ok=False, a ValueError must be raised."""
        mw._post = lambda path, data=None, headers=None: {
            "ok": False,
            "error": "Insufficient balance",
        }

        with pytest.raises(ValueError, match="Place order failed"):
            mw.place_order(sample_order)

    def test_raises_connection_error_when_no_response(self, mw, sample_order):
        """When _post returns None (e.g. timeout / refused), a ConnectionError must be raised."""
        mw._post = lambda path, data=None, headers=None: None

        with pytest.raises(ConnectionError):
            mw.place_order(sample_order)


class TestIsMarketOpen:
    """Verify is_market_open() boundary conditions — no real HTTP needed."""

    def _stub_time(self, mw, iso: str):
        mw.get_system_time = lambda **kw: {"mock_current_time": iso}

    def test_weekday_within_hours_is_open(self, mw):
        """Monday 10:00 is within trading hours."""
        self._stub_time(mw, "2024-01-15T10:00:00")  # Monday
        assert mw.is_market_open() is True

    def test_weekday_before_open_is_closed(self, mw):
        """Monday 08:59 is before market opens."""
        self._stub_time(mw, "2024-01-15T08:59:00")
        assert mw.is_market_open() is False

    def test_weekday_after_close_is_closed(self, mw):
        """Monday 13:31 is after market closes."""
        self._stub_time(mw, "2024-01-15T13:31:00")
        assert mw.is_market_open() is False

    def test_weekend_is_closed(self, mw):
        """Saturday 10:00 is weekend — market closed regardless of time."""
        self._stub_time(mw, "2024-01-13T10:00:00")  # Saturday
        assert mw.is_market_open() is False


class TestCancelOrder:
    """Verify cancel_order() correctly maps the server response."""

    def test_parses_cancelled_response(self, mw):
        """A CANCELLED response must be mapped to an OrderResult with the enum status."""
        mw._post = lambda path, data=None, headers=None: {
            "result": {
                "status": "CANCELLED",
                "message": "order cancelled",
                "metadata": {},
                "linked_order": "order-abc",
            }
        }

        result = mw.cancel_order("order-abc")

        assert result.status == OrderStatus.CANCELLED
        assert result.linked_order == "order-abc"
        assert result.message == "order cancelled"
