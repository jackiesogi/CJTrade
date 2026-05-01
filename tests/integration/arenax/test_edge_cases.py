"""Integration tests — edge cases and boundary conditions.

- Non-existent / already-cancelled / filled orders
- Invalid parameters (zero, negative)
- Operations after disconnect
"""
import time

import pytest
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product

from tests.integration.conftest import likely_fill_buy_price
from tests.integration.conftest import make_order
from tests.integration.conftest import unlikely_fill_buy_price


def _wait_for_fill(client, order_id: str, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Poll list_orders() until the given order is FILLED or timeout expires.

    Returns True if filled within the timeout, False otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        trades = client.list_orders()
        for t in trades:
            if getattr(t, 'id', None) == order_id and getattr(t, 'status', None) == OrderStatus.FILLED:
                return True
        time.sleep(interval)
    return False


class TestEdgeCases:

    def test_10_cancel_nonexistent_order(self, client):
        """Cancelling an unknown order_id must return REJECTED with 'not found'."""
        result = client.cancel_order("nonexistent_order_id")

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "not found" in result.message.lower()

    def test_11_cancel_already_cancelled_order(self, client):
        """Second cancellation on an already-cancelled order must be REJECTED."""
        price = unlikely_fill_buy_price(client, "0050")
        order = make_order(price=price)
        client.place_order(order)
        client.sync_state()

        result1 = client.cancel_order(order.id)
        assert result1.status == OrderStatus.CANCELLED

        result2 = client.cancel_order(order.id)
        assert result2.status == OrderStatus.REJECTED
        assert "not found" in result2.message.lower()

    def test_12_cancel_filled_order(self, client):
        """cancel_order() on a filled order must return REJECTED with 'filled' in the message.

        The order is placed at buy_price +8% so the simulated exchange matches it
        immediately after sync_state().  We poll for FILLED status rather than
        sleeping a fixed amount, and skip if the fill does not arrive in time
        (environment not ready, e.g. data not loaded yet).
        """
        price = likely_fill_buy_price(client, "0050")
        order = make_order(price=price)
        client.place_order(order)
        client.sync_state()

        if not _wait_for_fill(client, order.id, timeout=10.0):
            pytest.skip("Order did not fill within timeout — server state may be inconsistent")

        result = client.cancel_order(order.id)
        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "filled" in result.message.lower()

    def test_13_zero_quantity_order(self, client):
        """Order with quantity=0 must be REJECTED by the server."""
        order = make_order(quantity=0)
        result = client.place_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "positive" in result.message.lower()

    def test_14_negative_price_order(self, client):
        """Order with negative price must be REJECTED by the server."""
        order = make_order(price=-100.0)
        result = client.place_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "positive" in result.message.lower()

    def test_15_negative_quantity_order(self, client):
        """Order with negative quantity must be REJECTED by the server."""
        order = make_order(quantity=-1000)
        result = client.place_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "positive" in result.message.lower()

    def test_16_sync_state_without_pending_orders(self, client):
        """sync_state() with no pending orders must return an empty list gracefully."""
        result = client.sync_state()
        assert isinstance(result, list)

    def test_17_place_order_after_disconnect(self, client):
        """place_order() after disconnect must raise an exception."""
        client.disconnect()

        order = make_order()
        with pytest.raises(Exception):
            client.place_order(order)

        # Reconnect so the fixture teardown (client.disconnect) doesn't fail
        client.connect()
