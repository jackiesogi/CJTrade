"""Integration tests — end-to-end order lifecycle and mixed operation sequences."""
from cjtrade.pkgs.models.order import OrderStatus

from tests.integration.conftest import get_order_from_db
from tests.integration.conftest import make_order
from tests.integration.conftest import unlikely_fill_buy_price


class TestLifecycle:

    def test_50_full_order_lifecycle(self, client):
        """place → sync_state → cancel all succeed and DB tracks each transition."""
        price = unlikely_fill_buy_price(client, "0050")
        order = make_order(price=price)

        place_result = client.place_order(order)
        assert place_result.status == OrderStatus.PLACED
        assert get_order_from_db(client, order.id)["status"] == "PLACED"

        commit_result = client.sync_state()
        assert isinstance(commit_result, list)
        assert get_order_from_db(client, order.id)["status"] in (
            "COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN"
        )

        cancel_result = client.cancel_order(order.id)
        assert cancel_result.status == OrderStatus.CANCELLED
        assert get_order_from_db(client, order.id)["status"] == "CANCELLED"

    def test_51_mixed_operations_sequence(self, client):
        """Place 3 orders, commit all, cancel the middle one; verify independent statuses."""
        order1 = make_order(symbol="0050")
        order2 = make_order(symbol="0056")
        order3 = make_order(symbol="2330")

        client.place_order(order1)
        client.place_order(order2)
        client.place_order(order3)
        client.sync_state()

        client.cancel_order(order2.id)

        committed = ("COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN")
        assert get_order_from_db(client, order1.id)["status"] in committed
        assert get_order_from_db(client, order2.id)["status"] == "CANCELLED"
        assert get_order_from_db(client, order3.id)["status"] in committed

        client.cancel_order(order1.id)
        client.cancel_order(order3.id)
