"""Normal operation tests for CJTrade Broker API

Tests basic, expected flows:
- Order placement
- Order commit
- Order cancellation
- Multiple orders
- Buy and sell operations
"""

from cjtrade.models.order import OrderAction, OrderStatus
from tests.cj_api.base import BaseBrokerTest
from tests.utils.test_formatter import get_log_buffer


class TestNormalOperations(BaseBrokerTest):
    """Test normal broker API operations"""

    def test_01_order_placement_basic(self):
        """Test basic order placement flow"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Basic order placement\n")

        order = self._create_test_order()
        result = self.client.place_order(order)

        # Verify result
        self.assertIsNotNone(result)
        self.assertIn(result.status, [OrderStatus.COMMITTED_WAIT_MARKET_OPEN, OrderStatus.PLACED])

        # Verify DB persistence
        db_order = self._get_order_from_db(order.id)
        self.assertIsNotNone(db_order)
        self.assertEqual(db_order['order_id'], order.id)
        self.assertEqual(db_order['product_id'], '0050')
        self.assertEqual(db_order['side'], 'OrderAction.BUY')

    def test_02_order_commit_flow(self):
        """Test order commit after placement"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Order commit flow\n")

        order = self._create_test_order()
        place_result = self.client.place_order(order)
        # After place: should be PLACED (pending commit)
        self.assertEqual(place_result.status, OrderStatus.PLACED)

        # Commit the order
        commit_results = self.client.commit_order()
        self.assertIsInstance(commit_results, list)
        self.assertGreater(len(commit_results), 0)

        # Verify status updated (depends on market hours)
        # - Market open: COMMITTED_WAIT_MATCHING
        # - Market closed: COMMITTED_WAIT_MARKET_OPEN
        db_order = self._get_order_from_db(order.id)
        self.assertIn(db_order['status'], ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN'])

    def test_03_order_cancellation(self):
        """Test order cancellation"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Order cancellation\n")

        # Place and commit order
        order = self._create_test_order()
        self.client.place_order(order)
        self.client.commit_order()

        # Cancel the order
        cancel_result = self.client.cancel_order(order.id)
        self.assertEqual(cancel_result.status, OrderStatus.CANCELLED)

        # Verify DB updated
        self.assertTrue(self._verify_order_consistency(order.id, 'CANCELLED'))

    def test_04_multiple_orders_sequential(self):
        """Test placing multiple orders sequentially"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Multiple orders sequential\n")

        order_ids = []
        for i in range(5):
            order = self._create_test_order(symbol="0050", price=100.0 + i)
            result = self.client.place_order(order)
            self.assertEqual(result.status, OrderStatus.PLACED)
            order_ids.append(order.id)

        # Commit all orders
        self.client.commit_order()

        # Verify all orders in DB
        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), 5)

        # Status depends on market hours
        for order_id in order_ids:
            self.assertTrue(self._verify_order_consistency(
                order_id,
                ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN']
            ))

    def test_05_buy_and_sell_operations(self):
        """Test buy and sell stock operations"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Buy and sell operations\n")

        # Test buy
        buy_result = self.client.buy_stock('2330', 3, 50.0, intraday_odd=True)
        self.assertIsInstance(buy_result, list)

        # Test sell
        sell_result = self.client.sell_stock('2330', 2, 55.0, intraday_odd=True)
        self.assertIsInstance(sell_result, list)

        # Verify orders in DB
        all_orders = self._get_all_orders_from_db()
        buy_orders = [o for o in all_orders if o['side'] == 'OrderAction.BUY']
        sell_orders = [o for o in all_orders if o['side'] == 'OrderAction.SELL']

        self.assertGreater(len(buy_orders), 0)
        self.assertGreater(len(sell_orders), 0)
