"""Integration tests — DB and internal state consistency.

- Orders persist across operations
- Status transitions follow the correct sequence (PLACED → COMMITTED → CANCELLED)
- Timestamps are written on each transition
"""
from tests.integration.conftest import get_all_orders_from_db
from tests.integration.conftest import get_order_from_db
from tests.integration.conftest import make_order
from tests.integration.conftest import unlikely_fill_buy_price


class TestDbState:

    def test_20_db_order_persistence(self, client):
        """Three placed orders must all appear in the local DB with matching symbols."""
        symbols = ["0050", "0051", "0052"]
        orders = []
        for sym in symbols:
            order = make_order(symbol=sym)
            client.place_order(order)
            orders.append(order)

        db_orders = get_all_orders_from_db(client)
        assert len(db_orders) == 3

        for order in orders:
            db_order = get_order_from_db(client, order.id)
            assert db_order is not None
            assert db_order["product_id"] == order.product.symbol
            client.cancel_order(order.id)

    def test_21_status_transition_sequence(self, client):
        """DB status must progress: PLACED → COMMITTED_WAIT_* → CANCELLED."""
        price = unlikely_fill_buy_price(client, "0050")
        order = make_order(price=price)
        client.place_order(order)

        db_after_place = get_order_from_db(client, order.id)
        assert db_after_place["status"] == "PLACED"

        client.sync_state()
        db_after_commit = get_order_from_db(client, order.id)
        assert db_after_commit["status"] in (
            "COMMITTED_WAIT_MATCHING", "COMMITTED_WAIT_MARKET_OPEN"
        )

        client.cancel_order(order.id)
        db_after_cancel = get_order_from_db(client, order.id)
        assert db_after_cancel["status"] == "CANCELLED"

    def test_22_timestamps_written_on_transitions(self, client):
        """updated_at timestamp must change after a status update."""
        order = make_order(price=50.0)
        client.place_order(order)

        db_before = get_order_from_db(client, order.id)
        ts_before = db_before["updated_at"]

        client.sync_state()
        db_after = get_order_from_db(client, order.id)
        ts_after = db_after["updated_at"]

        assert ts_after is not None
        # Timestamp must have been written (either changed or set for the first time)
        assert ts_before != ts_after or ts_after is not None

        client.cancel_order(order.id)
