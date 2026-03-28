"""Edge case tests for CJTrade Broker API

Tests unusual inputs and boundary conditions:
- Non-existent orders
- Already cancelled/filled orders
- Invalid parameters (zero, negative values)
- Disconnected state operations
- Extreme values
"""
import time

from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product

from tests.cj_api.base import BaseBrokerTest
from tests.utils.test_formatter import get_log_buffer


class TestEdgeCases(BaseBrokerTest):
    """Test edge cases and boundary conditions"""

    def test_10_cancel_nonexistent_order(self):
        """Test cancelling an order that doesn't exist"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Cancel non-existent order\n")

        fake_order_id = "nonexistent_order_id"
        result = self.client.cancel_order(fake_order_id)

        # Should handle gracefully
        self.assertIsNotNone(result)

    def test_11_cancel_already_cancelled_order(self):
        """Test cancelling an already cancelled order (idempotency)"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Cancel already cancelled order\n")

        order = self._create_test_order(test_case="11")
        self.client.place_order(order)
        self.client.commit_order()

        # First cancellation
        result1 = self.client.cancel_order(order.id)
        self.assertEqual(result1.status, OrderStatus.CANCELLED)

        # Second cancellation - should be idempotent
        result2 = self.client.cancel_order(order.id)
        # Result may vary, but should not crash

    def test_12_cancel_filled_order(self):
        """Test cancelling an order that is already filled"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Cancel filled order\n")

        # Price that will likely fill
        potential_fill_price = self.client.get_snapshots(products=[Product("0050")])[0].buy_price
        # A very high buy price that definitely will be filled immediately.
        order = self._create_test_order(price=potential_fill_price + potential_fill_price * 0.08, test_case="12")
        self.client.place_order(order)
        self.client.commit_order()

        # Wait for potential fill
        time.sleep(2)  # NOTE: currently `commit_order` will call `_check_if_any_order_filled`

        # Try to cancel
        result = self.client.cancel_order(order.id)
        # Should either reject or be already filled
        self.assertIsNotNone(result)
        self.assertIn(result.status, [OrderStatus.REJECTED])

    def test_13_invalid_order_parameters_zero_quantity(self):
        """Test order with zero quantity"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Zero quantity order\n")

        order = self._create_test_order(quantity=0, test_case="13")
        result = self.client.place_order(order)

        # Should be rejected or handled gracefully
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.REJECTED)

    def test_14_invalid_order_parameters_negative_price(self):
        """Test order with negative price"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Negative price order\n")

        order = self._create_test_order(price=-100.0, test_case="14")
        result = self.client.place_order(order)

        # Should be rejected
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.REJECTED)

    def test_15_invalid_order_parameters_negative_quantity(self):
        """Test order with negative quantity"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Negative quantity order\n")

        order = self._create_test_order(quantity=-1000, test_case="15")
        result = self.client.place_order(order)

        # Should be rejected
        self.assertIsNotNone(result)

    def test_16_commit_without_pending_orders(self):
        """Test committing when there are no pending orders"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Commit without pending orders\n")

        result = self.client.commit_order()

        # Should return empty list or handle gracefully
        # Note: Sinopac may return previously committed orders
        self.assertIsInstance(result, list)

    def test_17_place_order_after_disconnect(self):
        """Test placing order after disconnecting"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Place order after disconnect\n")

        self.client.disconnect()

        order = self._create_test_order(test_case="17")

        with self.assertRaises(Exception):
            self.client.place_order(order)

        # Reconnect for tearDown
        self.client.connect()

    def test_18_large_quantity_order(self):
        """Test order with very large quantity"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Large quantity order\n")

        order = self._create_test_order(quantity=999999, price=0.01, test_case="18")
        result = self.client.place_order(order)

        # Should handle or reject based on broker rules
        self.assertIsNotNone(result)

    def test_19_extreme_price_values(self):
        """Test orders with extreme price values"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Extreme price values\n")

        # Very high price (but small quantity)
        order1 = self._create_test_order(price=9999.99, quantity=1, test_case="19a")
        result1 = self.client.place_order(order1)
        self.assertIsNotNone(result1)

        # Very low price (but positive)
        order2 = self._create_test_order(price=0.01, quantity=100, test_case="19b")
        result2 = self.client.place_order(order2)
        self.assertIsNotNone(result2)
