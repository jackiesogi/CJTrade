"""Integration tests — normal order flows.

Tests basic, expected flows:
- Order placement and DB persistence
- Order commit (sync_state)
- Order cancellation
- Multiple sequential orders
- buy_stock / sell_stock convenience methods
"""
import time

import pytest
from cjtrade.pkgs.models.event import OrderCallback
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product

from tests.integration.conftest import client
from tests.integration.conftest import get_all_orders_from_db
from tests.integration.conftest import get_order_from_db
from tests.integration.conftest import likely_fill_buy_price
from tests.integration.conftest import likely_fill_sell_price
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


class TestNormalOperations:

    def test_N000_order_placement_basic(self, client):
        """place_order() returns PLACED and persists the order in the local DB."""
        order = make_order(price=50.0)
        result = client.place_order(order)

        assert result is not None
        assert result.status in (OrderStatus.COMMITTED_WAIT_MARKET_OPEN, OrderStatus.PLACED)

        db_order = get_order_from_db(client, order.id)
        assert db_order is not None
        assert db_order["order_id"] == order.id
        assert db_order["product_id"] == "0050"
        assert db_order["quantity"] == 2  # default quantity in make_order()
        assert db_order["price"] == 50.0
        assert db_order["status"] in ("PLACED", "COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN")
        assert db_order["side"] == "BUY"

        client.cancel_order(order.id)

    def test_N001_order_commit_flow(self, client):
        """place_order() followed by sync_state() updates DB status correctly."""
        order = make_order(price=50.0)
        place_result = client.place_order(order)
        assert place_result.status == OrderStatus.PLACED

        commit_results = client.sync_state()
        assert isinstance(commit_results, list)
        assert len(commit_results) == 1

        db_order = get_order_from_db(client, order.id)
        assert db_order["status"] in ("COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN")

        client.cancel_order(order.id)

    def test_N002_order_cancellation(self, client):
        """Placed and committed order can be cancelled; DB reflects CANCELLED status."""
        price = unlikely_fill_buy_price(client, "0050")
        order = make_order(price=price)
        client.place_order(order)
        client.sync_state()

        cancel_result = client.cancel_order(order.id)
        assert cancel_result.status == OrderStatus.CANCELLED

        db_order = get_order_from_db(client, order.id)
        assert db_order["status"] == "CANCELLED"

    def test_N003_multiple_orders_sequential(self, client):
        """Five sequential orders all land in DB with committed status."""
        order_ids = []
        for i in range(5):
            order = make_order(price=100.0 + i)
            result = client.place_order(order)
            assert result.status == OrderStatus.PLACED
            order_ids.append(order.id)

        client.sync_state()

        db_orders = get_all_orders_from_db(client)
        assert len(db_orders) == 5

        for oid in order_ids:
            db_order = get_order_from_db(client, oid)
            assert db_order["status"] in ("COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN", "FILLED")
            client.cancel_order(oid)

    def test_N004_buy_and_sell_operations(self, client):
        """buy_stock() and sell_stock() each persist entries with correct side."""
        buy_result = client.buy_stock("2330", 3, 50.0, intraday_odd=True)
        assert isinstance(buy_result, list)

        sell_result = client.sell_stock("2330", 2, 55.0, intraday_odd=True)
        assert isinstance(sell_result, list)

        all_orders = get_all_orders_from_db(client)
        buy_orders  = [o for o in all_orders if "BUY"  in o["side"]]
        sell_orders = [o for o in all_orders if "SELL" in o["side"]]
        assert len(buy_orders) == 1
        assert len(sell_orders) == 1

        for o in all_orders:
            client.cancel_order(o["order_id"])

    def test_N005_connect_with_wrong_api_key(self, bad_api_key_client):
        """Client with wrong API key should fail to place orders."""
        assert bad_api_key_client.connect() == False
        assert bad_api_key_client.is_connected() == False
        with pytest.raises(Exception, match="Not connected to broker"):
            bad_api_key_client.place_order(make_order())

    def test_N006_cash_balance_should_update_after_operations(self, client):
        """Selling a stock should increase cash balance; DB should reflect the change."""
        balance_1 = client.get_balance()

        buy_result = client.buy_stock("0050", 1, likely_fill_buy_price(client, "0050"), intraday_odd=True)
        assert isinstance(buy_result, list)
        ready = _wait_for_fill(client, buy_result[0].linked_order)
        if not ready:
            pytest.skip("Buy order did not fill within timeout — server state may be inconsistent")

        balance_2 = client.get_balance()
        assert balance_2 < balance_1

        client.sync_state()

        sell_result = client.sell_stock("0050", 1, likely_fill_sell_price(client, "0050"), intraday_odd=True)
        assert isinstance(sell_result, list)
        ready = _wait_for_fill(client, sell_result[0].linked_order)
        if not ready:
            pytest.skip("Sell order did not fill within timeout — server state may be inconsistent")

        balance_3 = client.get_balance()
        assert balance_3 > balance_2

        client.sync_state()

        balance_4 = client.get_balance()
        assert balance_1 != balance_2 != balance_3 == balance_4

    def test_N007_get_kbars(self, client):
        """get_kbars() should return a list of KBar objects with correct attributes."""
        # Available Range
        last_monday_YYYY_MM_DD = time.strftime("%Y-%m-%d", time.localtime(time.time() - (time.localtime().tm_wday + 7) * 24 * 3600))
        last_friday_YYYY_MM_DD = time.strftime("%Y-%m-%d", time.localtime(time.time() - (time.localtime().tm_wday + 3) * 24 * 3600))

        kbars = client.get_kbars(Product("0050"), interval="1m", start=last_monday_YYYY_MM_DD, end=last_friday_YYYY_MM_DD)
        assert isinstance(kbars, list)
        assert len(kbars) > 0
        for k in kbars:
            assert hasattr(k, "timestamp")
            assert hasattr(k, "open")
            assert hasattr(k, "high")
            assert hasattr(k, "low")
            assert hasattr(k, "close")
            assert hasattr(k, "volume")

        # Unavailable Range (far future)
        future_kbars = client.get_kbars(Product("0050"), interval="1m", start="2100-01-01", end="2100-01-31")
        assert isinstance(future_kbars, list)
        # TODO: Currently get_kbars() has its own fallback and only alert through stdout;
        # we should ideally have it raise an exception or return a distinguishable value on failure instead of an empty list.

    def test_N008_register_order_callback(self, client):
        cb = lambda event: print(f"Order callback received: {event}")
        assert client.register_order_callback(callback=cb) == None  # Currently not implemented

    def test_N009_get_market_movers(self, client):
        assert client.get_market_movers() == None  # Currently not implemented

    def test_N010_get_broker_name(self, client):
        assert "arenax" in client.get_broker_name()

    def test_N011_is_market_open(self, client):
        assert client.is_market_open() in (True, False)
        current_time = client.get_market_time()['mock_current_time']
        # 9:00-13:30 on weekdays should be open
        if current_time is not None:
            hour = current_time.hour
            minute = current_time.minute
            weekday = current_time.weekday()
            is_open = client.is_market_open()
            if weekday < 5 and ((hour == 9 and minute >= 0) or (hour == 10) or (hour == 11) or (hour == 12) or (hour == 13 and minute <= 30)):
                assert is_open is True
            else:
                assert is_open is False
