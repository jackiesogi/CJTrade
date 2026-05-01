"""Unit tests for ArenaXBrokerAPI_v2.

Pattern demonstrated here:
  - Inject a StubMiddleWare via the `middleware=` constructor argument.
  - Bypass connect() by setting broker.db and broker._connected directly,
    isolating the method under test from network and filesystem.
  - Use pytest's tmp_path fixture for a real-but-temporary SQLite file.

To run only this file:
    pytest tests/unit/pkgs/brokers/arenax/test_broker_api.py
"""
from datetime import datetime

import pytest
from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import prepare_cjtrade_tables
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType


# ── Stub middleware ───────────────────────────────────────────────────────────
# Extend this class in individual tests when you need different behaviour.

class StubMiddleWare:
    """Minimal in-memory stub for ArenaXMiddleWare.

    Every method returns a safe, predictable value so tests can focus on the
    broker API logic rather than HTTP details.
    """

    def __init__(self):
        self.last_login_key = None

    def login(self, api_key: str):
        self.last_login_key = api_key

    def logout(self):
        pass

    def get_system_time(self) -> dict:
        return {
            "mock_current_time": "2024-01-15T10:30:00",
            "real_current_time": "2026-05-01T10:30:00",
            "mock_init_time":    "2024-01-15T09:00:00",
            "real_init_time":    "2026-05-01T09:00:00",
        }

    def is_market_open(self) -> bool:
        return True

    def account_summary(self) -> dict:
        return {"balance": 1_000_000.0, "positions": [], "orders": []}

    def place_order(self, order, **kwargs) -> OrderResult:
        return OrderResult(
            status=OrderStatus.PLACED,
            message="ok",
            metadata={},
            linked_order="",
            id=order.id,
        )

    def cancel_order(self, order_id: str, **kwargs) -> OrderResult:
        return OrderResult(
            status=OrderStatus.CANCELLED,
            message="cancelled",
            metadata={},
            linked_order=order_id,
            id=order_id,
        )

    def sync_state(self, order_id: str, **kwargs) -> OrderResult:
        return OrderResult(
            status=OrderStatus.COMMITTED_WAIT_MATCHING,
            message="committed",
            metadata={},
            linked_order=order_id,
            id=order_id,
        )


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_mw():
    return StubMiddleWare()


@pytest.fixture
def tmp_db(tmp_path):
    """In-file SQLite DB with all cjtrade tables pre-created. Cleaned up automatically."""
    conn = connect_sqlite(database=str(tmp_path / "test.db"))
    prepare_cjtrade_tables(conn)
    return conn


@pytest.fixture
def api(stub_mw, tmp_db):
    """ArenaXBrokerAPI_v2 wired to stub middleware and a temp DB, pre-connected."""
    broker = ArenaXBrokerAPI_v2(middleware=stub_mw, api_key="testkey", username="tester")
    broker.db = tmp_db
    broker._connected = True
    return broker


@pytest.fixture
def sample_order():
    return Order(
        product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol="2330"),
        action=OrderAction.BUY,
        price=500.0,
        quantity=1,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.Common,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGetSystemTime:
    def test_returns_datetime_objects(self, api):
        """get_system_time() must parse ISO strings from middleware into datetime objects."""
        t = api.get_system_time()

        assert isinstance(t["mock_current_time"], datetime)
        assert isinstance(t["real_current_time"], datetime)
        assert t["mock_current_time"] == datetime(2024, 1, 15, 10, 30, 0)
        assert t["real_current_time"] == datetime(2026, 5, 1, 10, 30, 0)
