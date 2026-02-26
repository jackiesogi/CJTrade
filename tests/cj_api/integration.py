"""Integration tests for CJTrade Broker API

Tests complete workflows combining multiple operations:
- Full order lifecycle
- Mixed operation sequences
- End-to-end flows
"""

from cjtrade.models.order import OrderStatus
from tests.cj_api.base import BaseBrokerTest
from tests.utils.test_formatter import get_log_buffer


class TestIntegrationFlows(BaseBrokerTest):
    """Test complete integration workflows"""

    def test_50_full_order_lifecycle(self):
        """Test complete order lifecycle: place -> commit -> cancel"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Full order lifecycle\n")

        # Place
        order = self._create_test_order()
        place_result = self.client.place_order(order)
        self.assertEqual(place_result.status, OrderStatus.PLACED)
        self.assertTrue(self._verify_order_consistency(order.id, 'PLACED'))

        # Commit
        commit_result = self.client.commit_order()
        self.assertIsInstance(commit_result, list)
        # Status depends on market hours
        self.assertTrue(self._verify_order_consistency(
            order.id,
            ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN']
        ))

        # Cancel
        cancel_result = self.client.cancel_order(order.id)
        self.assertEqual(cancel_result.status, OrderStatus.CANCELLED)
        self.assertTrue(self._verify_order_consistency(order.id, 'CANCELLED'))

    def test_51_mixed_operations_sequence(self):
        """Test mixed sequence of operations"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Mixed operations sequence\n")

        # Place multiple orders
        order1 = self._create_test_order(symbol="0050")
        order2 = self._create_test_order(symbol="0056")
        order3 = self._create_test_order(symbol="2330")

        self.client.place_order(order1)
        self.client.place_order(order2)
        self.client.place_order(order3)

        # Commit all
        self.client.commit_order()

        # Cancel one
        self.client.cancel_order(order2.id)

        # Verify states (status depends on market hours)
        self.assertTrue(self._verify_order_consistency(
            order1.id,
            ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN']
        ))
        self.assertTrue(self._verify_order_consistency(order2.id, 'CANCELLED'))
        self.assertTrue(self._verify_order_consistency(
            order3.id,
            ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN']
        ))
