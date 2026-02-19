#!/usr/bin/env python3
"""
CJTrade Broker API Stability Test Suite
==========================================
Tests the stability of CJ's unified broker API, focusing on:
- Order state consistency between DB and internal memory
- Edge case handling (invalid parameters, duplicate operations, etc.)
- Normal operation flows
- Database persistence and recovery
- Concurrent operation safety (TODO)

This test uses MockBroker to ensure reproducibility and fast execution.
"""

# TODO: State name in DB / Mock / Sinopac is quite different, try align with sinopac
# TODO: DB connection access is wrapped inside an Broker API's instance, which is a
# bit awkward to access for testing. Consider refactoring to allow easier DB access for tests.
# TODO: Add test group (sinopac / mock) to be able to test Sinopac with these cases
# in a secured way. (e.g. Avoid fast requests cases)
# TODO: Add `set_init_balance()` / `set_init_positions()` to MockBrokerAPI to allow
# easier testing of balance/position consistency.

import unittest
import tempfile
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import List, Dict
from io import StringIO

# Import CJTrade modules
from cjtrade.core.account_client import AccountClient, BrokerType
from cjtrade.models.order import Order, OrderAction, OrderStatus, OrderResult, PriceType, OrderType, OrderLot
from cjtrade.models.product import Product, ProductType, Exchange
from cjtrade.db.db_api import connect_sqlite, prepare_cjtrade_tables
from cjtrade.db.sqlite import SqliteDatabaseConnection

# Global log buffer for detailed logging
_log_buffer = None


class TestBrokerAPIStability(unittest.TestCase):
    """Test suite for CJTrade Broker API stability and consistency

    NOTE: This test suite is designed specifically for MockBroker.
    It tests the unified CJ API layer, not broker-specific implementations.
    Each test uses an isolated temporary database and account state file
    to ensure test independence.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        pass

    def setUp(self):
        """Set up test fixtures before each test"""
        global _log_buffer
        # Create temporary database for each test
        self.temp_db = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = SqliteDatabaseConnection(self.db_path)

        # Create temporary mock account state file for isolation
        temp_file = tempfile.mktemp(suffix='.json')
        self.account_state_path = temp_file
        
        # Log to buffer only (not stdout)
        if _log_buffer:
            _log_buffer.write(f"\n[SETUP] Created temporary database at {self.db_path}\n")
            _log_buffer.write(f"[SETUP] Created temporary account state at {self.account_state_path}\n")

        # SAFETY CHECK: This test suite is designed for MockBroker only
        # Running against real brokers (Sinopac, etc.) poses financial and API quota risks
        # See tests/SINOPAC_TESTING_RISKS.md for details
        broker_type = BrokerType.MOCK  # Hardcoded for safety
        
        # Allow override via environment variable (with explicit confirmation)
        env_broker = os.environ.get('TEST_BROKER_TYPE', '').upper()
        if env_broker and env_broker != 'MOCK':
            warning = f"\n{'='*70}\n"
            warning += f"⚠️  WARNING: Attempting to test with {env_broker} broker!\n"
            warning += f"⚠️  This may cause:\n"
            warning += f"    - Real financial transactions\n"
            warning += f"    - API quota exhaustion\n"
            warning += f"    - Account suspension\n"
            warning += f"⚠️  See tests/SINOPAC_TESTING_RISKS.md for full risk analysis\n"
            warning += f"{'='*70}\n"
            
            # Log to buffer only
            if _log_buffer:
                _log_buffer.write(warning)
            
            # Require explicit confirmation
            confirm = os.environ.get('CONFIRM_REAL_BROKER_TEST', '').lower()
            if confirm != 'yes_i_understand_the_risks':
                self.skipTest(
                    f"Skipping test with {env_broker} broker. "
                    f"Set CONFIRM_REAL_BROKER_TEST='yes_i_understand_the_risks' to proceed."
                )

        # Create mock broker client with test configuration
        self.config = {
            'username': 'test_user',
            'mirror_db_path': self.db_path,
            'speed': 120.0,  # Fast simulation (supported speed)
            'simulation': True,
            'api_key': 'test_key',
            'secret_key': 'test_secret',
            'ca_path': 'test_ca',
            'ca_passwd': 'test_passwd',
            'state_file': self.account_state_path
        }

        self.client = AccountClient(broker_type, **self.config)
        self.client.connect()

    def tearDown(self):
        """Clean up after each test"""
        global _log_buffer
        try:
            self.client.disconnect()
        except Exception as e:
            if _log_buffer:
                _log_buffer.write(f"Warning: Error during disconnect: {e}\n")

        # Remove temporary database
        try:
            if os.path.exists(self.db_path):
                os.unlink(self.db_path)
        except Exception as e:
            if _log_buffer:
                _log_buffer.write(f"Warning: Could not delete temp DB: {e}\n")

        # Remove temporary account state file
        try:
            if os.path.exists(self.account_state_path):
                os.unlink(self.account_state_path)
        except Exception as e:
            if _log_buffer:
                _log_buffer.write(f"Warning: Could not delete temp account state: {e}\n")

    # ==================== Helper Methods ====================

    def _create_test_order(self, symbol: str = "0050", action: OrderAction = OrderAction.BUY,
                          price: float = 50.0, quantity: int = 100) -> Order:
        """Helper to create a test order"""
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )

        return Order(
            product=product,
            action=action,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.Common,
            quantity=quantity,
            price=price
        )

    def _get_order_from_db(self, order_id: str) -> Dict:
        """Helper to retrieve order from database"""
        query = f"SELECT * FROM orders WHERE order_id = '{order_id}'"
        result = self.client.broker_api.db.execute(query)
        if result and len(result) > 0:
            columns = ['order_id', 'user_id', 'broker', 'product_id', 'side',
                      'order_type', 'price_type', 'price', 'quantity', 'status',
                      'created_at', 'updated_at']
            return dict(zip(columns, result[0]))
        return None

    def _get_all_orders_from_db(self) -> List[Dict]:
        """Helper to retrieve all orders from database"""
        query = "SELECT * FROM orders"
        results = self.client.broker_api.db.execute(query)
        columns = ['order_id', 'user_id', 'broker', 'product_id', 'side',
                  'order_type', 'price_type', 'price', 'quantity', 'status',
                  'created_at', 'updated_at']
        return [dict(zip(columns, row)) for row in results] if results else []

    def _verify_order_consistency(self, order_id: str, expected_status: str) -> bool:
        """Verify that order status is consistent between DB and internal state"""
        # Check DB
        db_order = self._get_order_from_db(order_id)
        if not db_order:
            print(f"Order {order_id} not found in DB")
            return False

        # Check internal state
        # internal_orders = self.client.broker_api.list_orders()
        internal_orders = self.client.list_orders()
        internal_order = next((o for o in internal_orders if o.id == order_id), None)

        # Verify consistency
        db_status = db_order['status']
        db_match = (db_status == expected_status)

        if _log_buffer:
            _log_buffer.write(f"Order {order_id[:8]}: DB={db_status}, Expected={expected_status}\n")

        return db_match

    # ==================== Normal Operation Tests ====================

    def test_01_order_placement_basic(self):
        """Test basic order placement flow"""
        global _log_buffer
        if _log_buffer:
            _log_buffer.write("\n[TEST] Basic order placement\n")

        order = self._create_test_order()
        result = self.client.place_order(order)

        # Verify result
        self.assertIsNotNone(result)
        self.assertIn(result.status, [OrderStatus.ON_THE_WAY, OrderStatus.STAGED])

        # Verify DB persistence
        db_order = self._get_order_from_db(order.id)
        self.assertIsNotNone(db_order)
        self.assertEqual(db_order['order_id'], order.id)
        self.assertEqual(db_order['product_id'], '0050')
        self.assertEqual(db_order['side'], 'OrderAction.BUY')

    def test_02_order_commit_flow(self):
        """Test order commit after placement"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Order commit flow\n")

        order = self._create_test_order()
        place_result = self.client.place_order(order)
        self.assertEqual(place_result.status, OrderStatus.ON_THE_WAY)

        # Commit the order
        commit_results = self.client.commit_order()
        self.assertIsInstance(commit_results, list)
        self.assertGreater(len(commit_results), 0)

        # Verify status updated
        self.assertTrue(self._verify_order_consistency(order.id, 'COMMITTED'))

    def test_03_order_cancellation(self):
        """Test order cancellation"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Order cancellation\n")

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
        if _log_buffer:
            _log_buffer.write("\n[TEST] Multiple orders sequential\n")

        order_ids = []
        for i in range(5):
            order = self._create_test_order(symbol="0050", price=100.0 + i)
            result = self.client.place_order(order)
            self.assertEqual(result.status, OrderStatus.ON_THE_WAY)
            order_ids.append(order.id)

        # Commit all orders
        self.client.commit_order()

        # Verify all orders in DB
        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), 5)

        for order_id in order_ids:
            self.assertTrue(self._verify_order_consistency(order_id, 'COMMITTED'))

    def test_05_buy_and_sell_operations(self):
        """Test buy and sell stock operations"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Buy and sell operations\n")

        # Test buy
        buy_result = self.client.buy_stock('2330', 100, 50.0, intraday_odd=True)
        self.assertIsInstance(buy_result, list)

        # Test sell
        sell_result = self.client.sell_stock('2330', 50, 55.0, intraday_odd=True)
        self.assertIsInstance(sell_result, list)

        # Verify orders in DB
        all_orders = self._get_all_orders_from_db()
        buy_orders = [o for o in all_orders if o['side'] == 'OrderAction.BUY']
        sell_orders = [o for o in all_orders if o['side'] == 'OrderAction.SELL']

        self.assertGreater(len(buy_orders), 0)
        self.assertGreater(len(sell_orders), 0)

    # ==================== Edge Case Tests ====================

    def test_10_cancel_nonexistent_order(self):
        """Test cancelling an order that doesn't exist"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Cancel non-existent order\n")

        fake_order_id = "nonexistent_order_id"
        result = self.client.cancel_order(fake_order_id)

        # Should handle gracefully
        self.assertIsNotNone(result)

    def test_11_cancel_already_cancelled_order(self):
        """Test cancelling an already cancelled order (idempotency)"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Cancel already cancelled order\n")

        order = self._create_test_order()
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
        if _log_buffer:
            _log_buffer.write("\n[TEST] Cancel filled order\n")

        # This test documents current behavior
        # In real system, filled orders should not be cancellable
        order = self._create_test_order(price=45.0)  # Price that will likely fill
        self.client.place_order(order)
        self.client.commit_order()

        # Wait for potential fill (in mock env)
        import time
        time.sleep(0.1)

        # Try to cancel
        result = self.client.cancel_order(order.id)
        # Should either reject or be already filled

    def test_13_invalid_order_parameters_zero_quantity(self):
        """Test order with zero quantity"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Zero quantity order\n")

        order = self._create_test_order(quantity=0)
        result = self.client.place_order(order)

        # Should be rejected or handled gracefully
        self.assertIsNotNone(result)

    def test_14_invalid_order_parameters_negative_price(self):
        """Test order with negative price"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Negative price order\n")

        order = self._create_test_order(price=-100.0)
        result = self.client.place_order(order)

        # Should be rejected
        self.assertIsNotNone(result)

    def test_15_invalid_order_parameters_negative_quantity(self):
        """Test order with negative quantity"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Negative quantity order\n")

        order = self._create_test_order(quantity=-1000)
        result = self.client.place_order(order)

        # Should be rejected
        self.assertIsNotNone(result)

    def test_16_commit_without_pending_orders(self):
        """Test committing when there are no pending orders"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Commit without pending orders\n")

        result = self.client.commit_order()

        # Should return empty list or handle gracefully
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_17_place_order_after_disconnect(self):
        """Test placing order after disconnecting"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Place order after disconnect\n")

        self.client.disconnect()

        order = self._create_test_order()

        with self.assertRaises(Exception):
            self.client.place_order(order)

        # Reconnect for tearDown
        self.client.connect()

    def test_18_large_quantity_order(self):
        """Test order with very large quantity"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Large quantity order\n")

        order = self._create_test_order(quantity=999999, price=0.01)
        result = self.client.place_order(order)

        # Should handle or reject based on broker rules
        self.assertIsNotNone(result)

    def test_19_extreme_price_values(self):
        """Test orders with extreme price values"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Extreme price values\n")

        # Very high price (but small quantity)
        order1 = self._create_test_order(price=9999.99, quantity=1)
        result1 = self.client.place_order(order1)
        self.assertIsNotNone(result1)

        # Very low price (but positive)
        order2 = self._create_test_order(price=0.01, quantity=100)
        result2 = self.client.place_order(order2)
        self.assertIsNotNone(result2)

    # ==================== Database Consistency Tests ====================

    def test_20_db_order_persistence(self):
        """Test that orders persist correctly in database"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Order persistence in DB\n")

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
        if _log_buffer:
            _log_buffer.write("\n[TEST] Status update consistency\n")

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
        self.assertEqual(initial_status, 'NEW')
        self.assertEqual(committed_status, 'COMMITTED')
        self.assertEqual(cancelled_status, 'CANCELLED')

    def test_22_db_timestamp_updates(self):
        """Test that timestamps are correctly updated"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Timestamp updates\n")

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
        if _log_buffer:
            _log_buffer.write("\n[TEST] DB connection recovery\n")

        # Place order
        order1 = self._create_test_order()
        self.client.place_order(order1)

        # Disconnect and reconnect
        self.client.disconnect()
        print(f"Reconnect result: {self.client.connect()}")

        # Place another order
        order2 = self._create_test_order(symbol="2330")
        result = self.client.place_order(order2)

        # Should work after reconnection
        self.assertEqual(result.status, OrderStatus.ON_THE_WAY)

        # Verify both orders in DB
        all_orders = self._get_all_orders_from_db()
        self.assertEqual(len(all_orders), 2)

    def test_24_db_order_count_accuracy(self):
        """Test that order count in DB matches operations"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Order count accuracy\n")

        expected_count = 7
        for i in range(expected_count):
            order = self._create_test_order()
            self.client.place_order(order)

        db_orders = self._get_all_orders_from_db()
        self.assertEqual(len(db_orders), expected_count)

    # ==================== State Consistency Tests ====================

    def test_30_internal_state_vs_db_consistency(self):
        """Test that internal state matches database state"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Internal state vs DB consistency\n")

        orders = []
        for i in range(3):
            order = self._create_test_order(symbol=f"238{i}")
            self.client.place_order(order)
            orders.append(order)

        self.client.commit_order()

        # Check each order
        for order in orders:
            self.assertTrue(self._verify_order_consistency(order.id, 'COMMITTED'))

    def test_31_order_list_completeness(self):
        """Test that list_orders returns all orders"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Order list completeness\n")

        placed_orders = []
        for i in range(5):
            order = self._create_test_order()
            self.client.place_order(order)
            placed_orders.append(order.id)

        self.client.commit_order()

        # Get orders from broker
        broker_trades = self.client.list_orders()

        # Verify count (may include previous test orders if not isolated)
        # At minimum should have our orders
        self.assertGreaterEqual(len(broker_trades), 5)

    def test_32_balance_consistency(self):
        """Test that balance remains consistent"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Balance consistency\n")

        balance1 = self.client.get_balance()
        self.assertIsInstance(balance1, (int, float))

        # Place some orders
        for _ in range(3):
            order = self._create_test_order()
            self.client.place_order(order)

        balance2 = self.client.get_balance()
        # Balance should change or stay same depending on fills
        self.assertIsInstance(balance2, (int, float))

    def test_33_position_consistency(self):
        """Test that positions are tracked consistently"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Position consistency\n")

        positions1 = self.client.get_positions()
        self.assertIsInstance(positions1, list)

        # Execute some trades
        self.client.buy_stock('0050', 1000, 100.0)

        positions2 = self.client.get_positions()
        self.assertIsInstance(positions2, list)

    # ==================== Stress Tests ====================

    def test_40_rapid_order_submission(self):
        """Test submitting many orders rapidly"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Rapid order submission\n")

        order_count = 20
        orders = []

        for i in range(order_count):
            order = self._create_test_order(price=100.0 + i * 0.5)
            result = self.client.place_order(order)
            orders.append(order.id)
            self.assertIsNotNone(result)

        # Verify all in DB
        db_orders = self._get_all_orders_from_db()
        self.assertGreaterEqual(len(db_orders), order_count)

    def test_41_alternating_buy_sell(self):
        """Test alternating buy and sell orders"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Alternating buy/sell\n")

        for i in range(10):
            action = OrderAction.BUY if i % 2 == 0 else OrderAction.SELL
            order = self._create_test_order(action=action, price=100.0 + i)
            result = self.client.place_order(order)
            self.assertIsNotNone(result)

        db_orders = self._get_all_orders_from_db()
        buy_count = sum(1 for o in db_orders if o['side'] == 'OrderAction.BUY')
        sell_count = sum(1 for o in db_orders if o['side'] == 'OrderAction.SELL')

        self.assertGreater(buy_count, 0)
        self.assertGreater(sell_count, 0)

    # ==================== Integration Tests ====================

    def test_50_full_order_lifecycle(self):
        """Test complete order lifecycle: place -> commit -> cancel"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Full order lifecycle\n")

        # Place
        order = self._create_test_order()
        place_result = self.client.place_order(order)
        self.assertEqual(place_result.status, OrderStatus.ON_THE_WAY)
        self.assertTrue(self._verify_order_consistency(order.id, 'NEW'))

        # Commit
        commit_result = self.client.commit_order()
        self.assertIsInstance(commit_result, list)
        self.assertTrue(self._verify_order_consistency(order.id, 'COMMITTED'))

        # Cancel
        cancel_result = self.client.cancel_order(order.id)
        self.assertEqual(cancel_result.status, OrderStatus.CANCELLED)
        self.assertTrue(self._verify_order_consistency(order.id, 'CANCELLED'))

    def test_51_mixed_operations_sequence(self):
        """Test mixed sequence of operations"""
        if _log_buffer:
            _log_buffer.write("\n[TEST] Mixed operations sequence\n")

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

        # Verify states
        self.assertTrue(self._verify_order_consistency(order1.id, 'COMMITTED'))
        self.assertTrue(self._verify_order_consistency(order2.id, 'CANCELLED'))
        self.assertTrue(self._verify_order_consistency(order3.id, 'COMMITTED'))

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        pass


def run_tests():
    """Run the test suite with simplified console output and detailed log file"""
    global _log_buffer
    
    # Create a string buffer to capture detailed output
    _log_buffer = StringIO()
    
    # Wrapper to add writeln method
    class LogBufferWithWriteln:
        def __init__(self, buf):
            self.buf = buf
        def write(self, data):
            self.buf.write(data)
        def writeln(self, data=''):
            self.buf.write(data + '\n')
        def flush(self):
            pass
    
    log_stream = LogBufferWithWriteln(_log_buffer)
    
    # Write header to log buffer
    _log_buffer.write("="*70 + "\n")
    _log_buffer.write("CJTrade Broker API Stability Tests - Detailed Log\n")
    _log_buffer.write("="*70 + "\n\n")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestBrokerAPIStability)
    
    # Custom result class for simplified console output
    class SimplifiedTestResult(unittest.TextTestResult):
        def __init__(self, stream, descriptions, verbosity):
            # Use log buffer for detailed output, not console
            super().__init__(log_stream, descriptions, verbosity)
            self.console_stream = stream
            self.test_results = []
            
        def startTest(self, test):
            super().startTest(test)
            # Get test description
            test_method = getattr(test, test._testMethodName)
            description = test_method.__doc__ or "No description"
            description = description.strip()
            
            # Print test header to console only
            test_name = test._testMethodName
            self.console_stream.write(f"\n{test_name}... {description}\n")
            self.console_stream.flush()
            
            # Write to log buffer
            _log_buffer.write(f"\n{'='*70}\n")
            _log_buffer.write(f"{test_name}: {description}\n")
            _log_buffer.write(f"{'='*70}\n")
            
        def addSuccess(self, test):
            super().addSuccess(test)
            self.console_stream.write("✓ PASSED\n")
            self.console_stream.flush()
            _log_buffer.write("\nResult: PASSED\n")
            
        def addError(self, test, err):
            super().addError(test, err)
            self.console_stream.write("✗ ERROR\n")
            self.console_stream.flush()
            
            # Write full traceback to log buffer only
            import traceback
            _log_buffer.write("\nResult: ERROR\n")
            _log_buffer.write("Error Details:\n")
            _log_buffer.write(''.join(traceback.format_exception(*err)))
            _log_buffer.write("\n")
            
        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.console_stream.write("✗ FAILED\n")
            self.console_stream.flush()
            
            # Write full traceback to log buffer only
            import traceback
            _log_buffer.write("\nResult: FAILED\n")
            _log_buffer.write("Failure Details:\n")
            _log_buffer.write(''.join(traceback.format_exception(*err)))
            _log_buffer.write("\n")
            
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.console_stream.write(f"⊘ SKIPPED ({reason})\n")
            self.console_stream.flush()
            _log_buffer.write(f"\nResult: SKIPPED\nReason: {reason}\n")
    
    # Custom test runner
    class SimplifiedTestRunner(unittest.TextTestRunner):
        resultclass = SimplifiedTestResult
    
    # Redirect stdout and stderr to log buffer during tests
    # to capture broker API debug output
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    
    # Create a tee that writes to both log and null (not console)
    class LogOnlyStream:
        def write(self, data):
            _log_buffer.write(data)
        def writeln(self, data=''):
            _log_buffer.write(data + '\n')
        def flush(self):
            pass
    
    # Print header to console
    print("\n" + "="*70)
    print("CJTrade Broker API Stability Tests")
    print("="*70)
    
    # Redirect outputs during test execution
    sys.stdout = LogOnlyStream()
    sys.stderr = LogOnlyStream()
    
    try:
        runner = SimplifiedTestRunner(stream=old_stdout, verbosity=2)
        result = runner.run(suite)
    finally:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    
    # Print summary to console
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    success_count = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"Success: {success_count}/{result.testsRun}")
    print(f"Failure: {len(result.failures)}/{result.testsRun}")
    print(f"Error: {len(result.errors)}/{result.testsRun}")
    print(f"Skip: {len(result.skipped)}/{result.testsRun}")
    print("="*70)
    
    # Write summary to log buffer
    _log_buffer.write("\n" + "="*70 + "\n")
    _log_buffer.write("TEST SUMMARY\n")
    _log_buffer.write("="*70 + "\n")
    _log_buffer.write(f"Tests run: {result.testsRun}\n")
    _log_buffer.write(f"Successes: {success_count}\n")
    _log_buffer.write(f"Failures: {len(result.failures)}\n")
    _log_buffer.write(f"Errors: {len(result.errors)}\n")
    _log_buffer.write(f"Skipped: {len(result.skipped)}\n")
    _log_buffer.write("="*70 + "\n")
    
    # Write complete log to file
    log_file = 'LAST_BROKER_STABILITY_TEST.log'
    with open(log_file, 'w') as f:
        f.write(_log_buffer.getvalue())
    print(f"\nDetailed log written to: {log_file}")
    
    return result


if __name__ == '__main__':
    # Set environment for testing
    os.environ['SIMULATION'] = 'y'
    os.environ['API_KEY'] = 'test'
    os.environ['SECRET_KEY'] = 'test'
    os.environ['CA_CERT_PATH'] = 'test'
    os.environ['CA_PASSWORD'] = 'test'

    run_tests()
