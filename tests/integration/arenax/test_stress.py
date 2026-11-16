"""Integration tests — stress scenarios."""
from cjtrade.pkgs.models.order import OrderAction

from tests.integration.conftest import get_all_orders_from_db
from tests.integration.conftest import make_order


class TestStress:

    def test_fifty_rapid_orders_all_reach_the_db(self, client):
        """50 rapid place_order() calls must all appear in the DB."""
        order_ids = []
        for i in range(50):
            order = make_order(price=100.0 + i * 0.5)
            result = client.place_order(order)
            assert result is not None
            order_ids.append(order.id)

        db_orders = get_all_orders_from_db(client)
        assert len(db_orders) == 50

        for oid in order_ids:
            client.cancel_order(oid)

    def test_alternating_buy_and_sell_orders_split_evenly(self, client):
        """Alternating BUY/SELL orders must split evenly in the DB."""
        for i in range(50):
            action = OrderAction.BUY if i % 2 == 0 else OrderAction.SELL
            order = make_order(action=action, price=100.0 + i)
            client.place_order(order)

        db_orders = get_all_orders_from_db(client)
        buy_count  = sum(1 for o in db_orders if "BUY"  in o["side"])
        sell_count = sum(1 for o in db_orders if "SELL" in o["side"])
        assert buy_count == 25
        assert sell_count == 25

        for o in db_orders:
            client.cancel_order(o["order_id"])
