"""State consistency tests for CJTrade Broker API

Tests database and internal state consistency:
- DB order persistence
- Status update consistency
- Timestamp updates
- DB connection recovery
- Internal state vs DB consistency
- Balance and position tracking
"""
from tests.cj_api.base import BaseBrokerTest
from tests.utils.test_formatter import get_log_buffer


class TestStateConsistency(BaseBrokerTest):
    """Test database and internal state consistency"""

    def test_20_db_order_persistence(self):
        """Test that orders persist correctly in database"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Order persistence in DB\n")

        orders = []
        for i in range(3):
            order = self._create_test_order(symbol=f"00{50+i}")
            self.client.place_order(order)
            orders.append(order)

        # Verify all orders in DB
        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), 3)

        for order in orders:
            db_order = self._get_order_from_db(order.id)
            self.assertIsNotNone(db_order)
            self.assertEqual(db_order['product_id'], order.product.symbol)

    def test_21_db_status_update_consistency(self):
        """Test that status updates are consistent"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Status update consistency\n")

        order = self._create_test_order()
        self.client.place_order(order)

        # Initial status
        db_order1 = self._get_order_from_db(order.id)
        initial_status = db_order1['status']

        # Commit
        self.client.commit_order()
        db_order2 = self._get_order_from_db(order.id)
        committed_status = db_order2['status']

        # Cancel
        self.client.cancel_order(order.id)
        db_order3 = self._get_order_from_db(order.id)
        cancelled_status = db_order3['status']

        # Verify progression
        self.assertEqual(initial_status, 'PLACED')
        # Committed status depends on market hours
        self.assertIn(committed_status, ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN'])
        self.assertEqual(cancelled_status, 'CANCELLED')

    def test_22_db_timestamp_updates(self):
        """Test that timestamps are correctly updated"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Timestamp updates\n")

        order = self._create_test_order()
        self.client.place_order(order)

        db_order1 = self._get_order_from_db(order.id)
        self.assertIsNotNone(db_order1['created_at'])
        self.assertIsNone(db_order1['updated_at'])

        # Update order
        self.client.commit_order()
        db_order2 = self._get_order_from_db(order.id)
        self.assertIsNotNone(db_order2['updated_at'])

    def test_23_db_connection_recovery(self):
        """Test database operations after reconnection"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] DB connection recovery\n")

        # Place order
        order1 = self._create_test_order()
        self.client.place_order(order1)

        # Disconnect and reconnect
        self.client.disconnect()
        self.client.connect()

        # Place another order
        order2 = self._create_test_order(symbol="2330")
        result = self.client.place_order(order2)

        # Should work after reconnection
        from cjtrade.models.order import OrderStatus
        self.assertEqual(result.status, OrderStatus.PLACED)

        # Verify both orders in DB
        all_orders = self._get_all_orders_from_db()
        self.assertEqual(len(all_orders), 2)

    def test_24_db_order_count_accuracy(self):
        """Test that order count in DB matches operations"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Order count accuracy\n")

        expected_count = 7
        for i in range(expected_count):
            order = self._create_test_order()
            self.client.place_order(order)

        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), expected_count)

    def test_30_internal_state_vs_db_consistency(self):
        """Test that internal state matches database state"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Internal state vs DB consistency\n")

        orders = []
        for i in range(2, 5):
            order = self._create_test_order(symbol=f"236{i}")
            self.client.place_order(order)
            orders.append(order)

        self.client.commit_order()

        # Check each order
        for order in orders:
            self.assertTrue(self._verify_order_consistency(
                order.id,
                ['COMMITTED_WAIT_MATCHING', 'COMMITTED_WAIT_MARKET_OPEN']
            ))

    def test_31_order_list_completeness(self):
        """Test that list_orders returns all orders"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Order list completeness\n")

        placed_orders = []
        for i in range(5):
            order = self._create_test_order()
            self.client.place_order(order)
            placed_orders.append(order.id)

        self.client.commit_order()

        # Get orders from broker
        broker_trades = self.client.list_orders()

        # Verify count
        self.assertGreaterEqual(len(broker_trades), 5)

    def test_32_balance_consistency(self):
        """Test that balance remains consistent"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Balance consistency\n")

        balance1 = self.client.get_balance()
        self.assertIsInstance(balance1, (int, float))

        # Place some orders
        for _ in range(3):
            order = self._create_test_order()
            self.client.place_order(order)

        balance2 = self.client.get_balance()
        self.assertIsInstance(balance2, (int, float))

    def test_33_position_consistency(self):
        """Test that positions are tracked consistently"""
        log_buffer = get_log_buffer()
        if log_buffer:
            log_buffer.write("\n[TEST] Position consistency\n")

        positions1 = self.client.get_positions()
        self.assertIsInstance(positions1, list)

        # Execute some trades
        self.client.buy_stock('0050', 3, 100.0, intraday_odd=True)

        positions2 = self.client.get_positions()
        self.assertIsInstance(positions2, list)
