# tests/integration/conftest.py
#
# Shared fixtures for all integration tests.
# All tests in this directory are skipped automatically if the ArenaX server
# is not reachable (no manual marking required).
#
# Run commands:
#   pytest tests/integration/           # all integration tests
#   pytest tests/integration/arenax/   # ArenaX-specific only
import pytest
import requests
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType


# ── Server availability ───────────────────────────────────────────────────────

def _is_arenax_running() -> bool:
    try:
        requests.get("http://localhost:8801/health", timeout=1)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_arenax():
    """Skip the entire integration suite when ArenaX server is not running."""
    if not _is_arenax_running():
        pytest.skip("ArenaX server not running — start it with `arenaxd` first")


# ── Client fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    """Connected AccountClient with isolated temp DB and state file per test."""
    config = {
        "username": "test_user",
        "mirror_db_path": str(tmp_path / "test.db"),
        "speed": 120.0,
        "api_key": "testkey123",
        "state_file": str(tmp_path / "state.json"),
    }
    c = AccountClient(BrokerType.ARENAX, **config)
    c.connect()
    yield c
    c.disconnect()


@pytest.fixture
def bad_api_key_client(tmp_path):
    """AccountClient with an intentionally invalid API key — NOT connected.
    Use this to assert that authentication errors raise the expected exception.

    Example::

        def test_bad_key_raises(bad_api_key_client):
            with pytest.raises(SomeAuthError):
                bad_api_key_client.connect()
    """
    config = {
        "username": "test_user",
        "mirror_db_path": str(tmp_path / "bad_key_test.db"),
        "speed": 120.0,
        "api_key": "INVALID_KEY_00000000",
        "state_file": str(tmp_path / "state.json"),
    }
    return AccountClient(BrokerType.ARENAX, **config)


# ── Order factory ─────────────────────────────────────────────────────────────

def make_order(
    symbol: str = "0050",
    action: OrderAction = OrderAction.BUY,
    price: float = 50.0,
    quantity: int = 2,
) -> Order:
    return Order(
        product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol=symbol),
        action=action,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd,
        quantity=quantity,
        price=price,
    )


# ── DB query helpers ──────────────────────────────────────────────────────────

_ORDER_COLUMNS = [
    "order_id", "user_id", "broker", "product_id", "side",
    "order_type", "price_type", "price", "quantity", "status",
    "created_at", "updated_at",
]


def get_order_from_db(client: AccountClient, order_id: str) -> dict | None:
    result = client.broker_api.db.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    )
    if result:
        return dict(zip(_ORDER_COLUMNS, result[0]))
    return None


def get_all_orders_from_db(client: AccountClient) -> list[dict]:
    results = client.broker_api.db.execute("SELECT * FROM orders")
    return [dict(zip(_ORDER_COLUMNS, row)) for row in results] if results else []


def unlikely_fill_buy_price(client: AccountClient, symbol: str) -> float:
    return round(client.get_snapshots([Product(symbol)])[0].close * 0.91, 2)


def unlikely_fill_sell_price(client: AccountClient, symbol: str) -> float:
    return round(client.get_snapshots([Product(symbol)])[0].close * 1.09, 2)


def likely_fill_buy_price(client: AccountClient, symbol: str) -> float:
    """Price high enough that the simulated exchange should match it immediately."""
    return round(client.get_snapshots([Product(symbol)])[0].buy_price * 1.08, 2)

def likely_fill_sell_price(client: AccountClient, symbol: str) -> float:
    """Price low enough that the simulated exchange should match it immediately."""
    return round(client.get_snapshots([Product(symbol)])[0].sell_price * 0.92, 2)
