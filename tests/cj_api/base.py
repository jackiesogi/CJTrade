# TODO: Clean up the code and test file structure, kinda messy now.
"""Base test class for CJTrade Broker API tests

This module provides a common base class with:
- Isolated temp database per test
- Isolated temp account state file per test
- Helper methods for creating orders and querying DB
- Safety checks to prevent accidental real broker testing
"""

import unittest
import tempfile
import os
import time
from typing import List, Dict

from cjtrade.core.account_client import AccountClient, BrokerType
from cjtrade.models.order import Order, OrderAction, OrderStatus, PriceType, OrderType, OrderLot
from cjtrade.models.product import Product, ProductType, Exchange
from cjtrade.db.sqlite import SqliteDatabaseConnection

# Import log buffer from formatter
from tests.utils.test_formatter import get_log_buffer


class BaseBrokerTest(unittest.TestCase):
    """Base class for CJTrade Broker API tests

    Provides:
    - setUp/tearDown with isolated temp DB and state file
    - Helper methods for creating orders
    - Helper methods for querying database
    - Safety checks for real broker testing
    """

    # Class variable to specify which broker to test (can be overridden via CLI)
    test_broker_type = None  # Will be set by main() or default to MOCK
    test_delay = 0  # Delay between tests for real brokers

    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        pass

    def setUp(self):
        """Set up test fixtures before each test"""
        log_buffer = get_log_buffer()

        # Create temporary database for each test
        self.temp_db = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = SqliteDatabaseConnection(self.db_path)

        # Create temporary mock account state file for isolation
        # Use mktemp to only generate path, let MockBroker initialize it
        temp_file = tempfile.mktemp(suffix='.json')
        self.account_state_path = temp_file

        # Log to buffer only (not stdout)
        if log_buffer:
            log_buffer.write(f"\n[SETUP] Created temporary database at {self.db_path}\n")
            log_buffer.write(f"[SETUP] Created temporary account state at {self.account_state_path}\n")

        # Get broker type from class variable (set via CLI) or default to MOCK
        broker_type = self.test_broker_type if self.test_broker_type is not None else BrokerType.MOCK

        # SAFETY CHECK: Warn and require confirmation when using real brokers
        if broker_type != BrokerType.MOCK:
            broker_name = broker_type.value.upper()
            warning = f"\n{'='*70}\n"
            warning += f"⚠️  WARNING: Testing with {broker_name} broker!\n"
            warning += f"⚠️  This may cause:\n"
            warning += f"    - Real financial transactions\n"
            warning += f"    - API quota exhaustion\n"
            warning += f"    - Account suspension\n"
            warning += f"⚠️  Make sure you have proper credentials configured\n"
            warning += f"{'='*70}\n"

            if log_buffer:
                log_buffer.write(warning)

            # Require explicit confirmation for real broker testing
            confirm = os.environ.get('CONFIRM_REAL_BROKER_TEST', '').lower()
            if confirm != 'yes_i_understand_the_risks':
                self.skipTest(
                    f"Skipping test with {broker_name} broker. "
                    f"Set CONFIRM_REAL_BROKER_TEST='yes_i_understand_the_risks' to proceed."
                )

        # Create broker client with test configuration
        self.config = {
            'username': os.environ.get('USERNAME', 'test_user'),
            'mirror_db_path': self.db_path,
            'speed': 120.0,
            'simulation': os.environ.get('SIMULATION', 'n').lower() == 'y',
            'api_key': os.environ.get('API_KEY', 'test_key'),
            'secret_key': os.environ.get('SECRET_KEY', 'test_secret'),
            'ca_path': os.environ.get('CA_CERT_PATH', 'test_ca'),
            'ca_passwd': os.environ.get('CA_PASSWORD', 'test_passwd'),
            'state_file': self.account_state_path
        }

        self.client = AccountClient(broker_type, **self.config)

        # Connect with retry mechanism for real brokers
        if broker_type != BrokerType.MOCK:
            self._connect_with_retry()
        else:
            self.client.connect()

    def tearDown(self):
        """Clean up after each test"""
        log_buffer = get_log_buffer()

        try:
            self.client.disconnect()
        except Exception as e:
            if log_buffer:
                log_buffer.write(f"Warning: Error during disconnect: {e}\n")

        # Add delay after disconnect for real brokers to allow connection cleanup
        if self.test_broker_type != BrokerType.MOCK and self.test_delay > 0:
            if log_buffer:
                log_buffer.write(f"[CLEANUP] Waiting {self.test_delay}s for connection cleanup...\n")
            time.sleep(self.test_delay)

        # Remove temporary database
        try:
            if os.path.exists(self.db_path):
                os.unlink(self.db_path)
        except Exception as e:
            if log_buffer:
                log_buffer.write(f"Warning: Could not delete temp DB: {e}\n")

        # Remove temporary account state file
        try:
            if os.path.exists(self.account_state_path):
                os.unlink(self.account_state_path)
        except Exception as e:
            if log_buffer:
                log_buffer.write(f"Warning: Could not delete temp account state: {e}\n")

    # ==================== Connection Management ====================

    def _connect_with_retry(self, max_retries=3, retry_delay=5):
        """Connect to broker with retry mechanism for handling connection limits

        Args:
            max_retries: Maximum number of connection attempts
            retry_delay: Seconds to wait between retries
        """
        log_buffer = get_log_buffer()

        for attempt in range(max_retries):
            try:
                self.client.connect()
                if log_buffer:
                    log_buffer.write(f"[CONNECTION] Successfully connected on attempt {attempt + 1}\n")
                return
            except Exception as e:
                error_msg = str(e)

                # Check if it's a connection limit error
                if "Too Many Connections" in error_msg or "status_code': 451" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (attempt + 1)  # Increasing backoff
                        if log_buffer:
                            log_buffer.write(
                                f"[CONNECTION] Attempt {attempt + 1} failed: Too many connections. "
                                f"Waiting {wait_time}s before retry...\n"
                            )
                        time.sleep(wait_time)
                    else:
                        raise ConnectionError(
                            f"Failed to connect after {max_retries} attempts. "
                            f"Broker connection limit reached. Try increasing --delay or reducing concurrent tests."
                        ) from e
                else:
                    # Other errors, don't retry
                    raise

    # ==================== Helper Methods ====================

    def _create_test_order(self, symbol: str = "0050", action: OrderAction = OrderAction.BUY,
                          price: float = 50.0, quantity: int = 2) -> Order:
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
            order_lot=OrderLot.IntraDayOdd,
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

    def _verify_order_consistency(self, order_id: str, expected_status) -> bool:
        """Verify that order status is consistent between DB and internal state

        Args:
            expected_status: Can be a string or a list of strings
        """
        log_buffer = get_log_buffer()

        # Check DB
        db_order = self._get_order_from_db(order_id)
        if not db_order:
            if log_buffer:
                log_buffer.write(f"Order {order_id} not found in DB\n")
            return False

        # Check internal state
        internal_orders = self.client.list_orders()
        internal_order = next((o for o in internal_orders if o.id == order_id), None)

        # Verify consistency
        db_status = db_order['status']

        # Support both single status and list of statuses
        if isinstance(expected_status, (list, tuple)):
            db_match = (db_status in expected_status)
        else:
            db_match = (db_status == expected_status)

        if log_buffer:
            log_buffer.write(f"Order {order_id[:8]}: DB={db_status}, Expected={expected_status}\n")

        return db_match

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        pass
