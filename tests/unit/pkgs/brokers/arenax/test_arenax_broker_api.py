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

    def get_market_time(self) -> dict:
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

class TestGetMarketTime:
    def test_returns_datetime_objects(self, api):
        """get_market_time() must parse ISO strings from middleware into datetime objects."""
        t = api.get_market_time()

        assert isinstance(t["mock_current_time"], datetime)
        assert isinstance(t["real_current_time"], datetime)
        assert t["mock_current_time"] == datetime(2024, 1, 15, 10, 30, 0)
        assert t["real_current_time"] == datetime(2026, 5, 1, 10, 30, 0)

    def test_get_system_time_alias_still_works(self, api):
        """The old name is deprecated but must keep returning the same thing."""
        assert api.get_system_time() == api.get_market_time()


# ── An unanswered account read ───────────────────────────────────────────────

class _SilentMiddleWare(StubMiddleWare):
    """A middleware that cannot reach the server.

    This is exactly what ArenaXMiddleWare does on any transport failure: it
    catches requests.exceptions.RequestException, prints, and returns None.
    """

    def account_summary(self):
        return None


class _HalfAnswerMiddleWare(StubMiddleWare):
    """The server answered, but without a balance in it."""

    def account_summary(self):
        return {"positions": [], "orders": []}


class TestUnreachableAccountRead:
    """A read that got no answer must not look like a zero balance.

    The engine samples the account every bar to feed its loss limit. When the
    server went away this used to surface two frames deep as
    `AttributeError: 'NoneType' object has no attribute 'get'`, which named
    nothing useful and which no caller could catch by type -- so one unanswered
    read ended an entire run.
    """

    def test_get_balance_raises_a_connection_error(self, tmp_db):
        broker = ArenaXBrokerAPI_v2(middleware=_SilentMiddleWare(),
                                    api_key="testkey", username="tester")
        broker.db, broker._connected = tmp_db, True
        with pytest.raises(ConnectionError) as excinfo:
            broker.get_balance()
        # The message has to say where, or it is no better than the
        # AttributeError it replaced.
        assert "did not answer" in str(excinfo.value)
        assert "/api/v1/account" in str(excinfo.value)

    def test_get_positions_raises_a_connection_error(self, tmp_db):
        broker = ArenaXBrokerAPI_v2(middleware=_SilentMiddleWare(),
                                    api_key="testkey", username="tester")
        broker.db, broker._connected = tmp_db, True
        with pytest.raises(ConnectionError):
            broker.get_positions()

    def test_it_is_not_an_attribute_error(self, tmp_db):
        """Guards the specific regression: AttributeError is what a caller
        cannot reasonably catch, so it must not come back."""
        broker = ArenaXBrokerAPI_v2(middleware=_SilentMiddleWare(),
                                    api_key="testkey", username="tester")
        broker.db, broker._connected = tmp_db, True
        for call in (broker.get_balance, broker.get_positions):
            try:
                call()
            except ConnectionError:
                pass
            except AttributeError as exc:            # pragma: no cover
                pytest.fail(f"{call.__name__} still raises AttributeError: {exc}")

    def test_balance_is_never_defaulted_to_zero(self, tmp_db):
        """0.0 would be acted on: it is below every loss limit, so the engine's
        kill switch would trip on a network blip."""
        broker = ArenaXBrokerAPI_v2(middleware=_HalfAnswerMiddleWare(),
                                    api_key="testkey", username="tester")
        broker.db, broker._connected = tmp_db, True
        with pytest.raises(ConnectionError) as excinfo:
            broker.get_balance()
        assert "no balance" in str(excinfo.value)

    def test_a_missing_position_list_is_empty_not_a_crash(self, tmp_db):
        """Positions are different from balance: "the account holds nothing" is
        a real answer a server can give, and `None` for the list is how it
        says so."""
        broker = ArenaXBrokerAPI_v2(middleware=_HalfAnswerMiddleWare(),
                                    api_key="testkey", username="tester")
        broker.db, broker._connected = tmp_db, True
        assert broker.get_positions() == []

    def test_a_good_answer_still_works(self, api):
        assert api.get_balance() == 1_000_000.0
        assert api.get_positions() == []
