"""Stress tests for CJTrade Broker API

Tests system behavior under load:
- Rapid order submission
- Alternating buy/sell operations
- High volume scenarios
"""

from cjtrade.models.order import OrderAction
from tests.cj_api.base import BaseBrokerTest
from tests.utils.test_formatter import get_log_buffer


class TestStressScenarios(BaseBrokerTest):
    """Test broker API under stress conditions"""

    def test_40_rapid_order_submission(self):
        """Test submitting many orders rapidly"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Rapid order submission\n")

        order_count = 10
        orders = []

        for i in range(order_count):
            order = self._create_test_order(price=100.0 + i * 0.5)
            result = self.client.place_order(order)
            orders.append(order.id)
            self.assertIsNotNone(result)

        # Verify all in DB
        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), order_count)

    def test_41_alternating_buy_sell(self):
        """Test alternating buy and sell orders"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Alternating buy/sell\n")

        for i in range(10):
            action = OrderAction.BUY if i % 2 == 0 else OrderAction.SELL
            order = self._create_test_order(action=action, price=100.0 + i)
            result = self.client.place_order(order)
            self.assertIsNotNone(result)

        db_orders = self._get_all_orders_from_db()
        buy_count = sum(1 for o in db_orders if o['side'] == 'OrderAction.BUY')
        sell_count = sum(1 for o in db_orders if o['side'] == 'OrderAction.SELL')

        self.assertEqual(buy_count, 5)
        self.assertEqual(sell_count, 5)
