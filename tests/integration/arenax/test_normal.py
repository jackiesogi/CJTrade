"""Integration tests — normal order flows.

Tests basic, expected flows:
- Order placement and DB persistence
- Order commit (sync_state)
- Order cancellation
- Multiple sequential orders
- buy_stock / sell_stock convenience methods
"""
import pytest
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus

from tests.integration.conftest import get_all_orders_from_db
from tests.integration.conftest import get_order_from_db
from tests.integration.conftest import make_order
from tests.integration.conftest import unlikely_fill_buy_price


class TestNormalOperations:

    def test_01_order_placement_basic(self, client):
        """place_order() returns PLACED and persists the order in the local DB."""
        order = make_order(price=50.0)
        result = client.place_order(order)

        assert result is not None
        assert result.status in (OrderStatus.COMMITTED_WAIT_MARKET_OPEN, OrderStatus.PLACED)

        db_order = get_order_from_db(client, order.id)
        assert db_order is not None
        assert db_order["order_id"] == order.id
        assert db_order["product_id"] == "0050"
        assert "BUY" in db_order["side"]

        client.cancel_order(order.id)

    def test_02_order_commit_flow(self, client):
        """place_order() followed by sync_state() updates DB status correctly."""
        order = make_order(price=50.0)
        place_result = client.place_order(order)
        assert place_result.status == OrderStatus.PLACED

        commit_results = client.sync_state()
        assert isinstance(commit_results, list)
        assert len(commit_results) > 0

        db_order = get_order_from_db(client, order.id)
        assert db_order["status"] in ("COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN")

        client.cancel_order(order.id)

    def test_03_order_cancellation(self, client):
        """Placed and committed order can be cancelled; DB reflects CANCELLED status."""
        price = unlikely_fill_buy_price(client, "0050")
        order = make_order(price=price)
        client.place_order(order)
        client.sync_state()

        cancel_result = client.cancel_order(order.id)
        assert cancel_result.status == OrderStatus.CANCELLED

        db_order = get_order_from_db(client, order.id)
        assert db_order["status"] == "CANCELLED"

    def test_04_multiple_orders_sequential(self, client):
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
            assert db_order["status"] in ("COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN")
            client.cancel_order(oid)

    def test_05_buy_and_sell_operations(self, client):
        """buy_stock() and sell_stock() each persist entries with correct side."""
        buy_result = client.buy_stock("2330", 3, 50.0, intraday_odd=True)
        assert isinstance(buy_result, list)

        sell_result = client.sell_stock("2330", 2, 55.0, intraday_odd=True)
        assert isinstance(sell_result, list)

        all_orders = get_all_orders_from_db(client)
        buy_orders  = [o for o in all_orders if "BUY"  in o["side"]]
        sell_orders = [o for o in all_orders if "SELL" in o["side"]]
        assert len(buy_orders) > 0
        assert len(sell_orders) > 0

        for o in all_orders:
            client.cancel_order(o["order_id"])
