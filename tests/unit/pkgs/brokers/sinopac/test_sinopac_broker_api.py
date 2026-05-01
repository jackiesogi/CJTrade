"""Unit tests for SinopacBrokerAPI and sinopac internal conversion functions.

Patterns demonstrated:
  - patch("shioaji.Shioaji") prevents any real Shioaji initialisation.
  - Replace broker.api with a MagicMock *after* construction for fine-grained control.
  - Use types.SimpleNamespace to build fake Shioaji return objects cheaply.
  - Pure-function tests (_from_sinopac_kbar) need no mock at all.

To run only this file:
    pytest tests/unit/pkgs/brokers/sinopac/test_sinopac_broker_api.py
"""
import types
from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_kbar
from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
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


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    conn = connect_sqlite(database=str(tmp_path / "test.db"))
    prepare_cjtrade_tables(conn)
    return conn


@pytest.fixture
def sample_order():
    return Order(
        product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol="2330"),
        action=OrderAction.BUY,
        price=500.0,
        quantity=1,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd,
    )


@pytest.fixture
def broker(tmp_db):
    """SinopacBrokerAPI wired to a mock Shioaji and a temp DB, pre-connected."""
    with patch("shioaji.Shioaji"):          # stop real Shioaji from initialising
        b = SinopacBrokerAPI(
            api_key="k", secret_key="s", ca_path="p", ca_passwd="pw"
        )
    b.api = MagicMock()                    # replace with controllable mock
    b.db = tmp_db
    b._connected = True
    return b


# ── Pure function: kbar timestamp correction ──────────────────────────────────

class TestFromSinopacKbar:
    """_from_sinopac_kbar must subtract 8 hours from every raw Shioaji timestamp."""

    def test_timestamp_offset_applied(self):
        """Returned datetime must equal datetime.fromtimestamp(ts_ns/1e9 - 8*3600)."""
        raw_ns = 1_705_291_200_000_000_000  # arbitrary nanosecond epoch value

        fake_kbar = types.SimpleNamespace(
            ts=[raw_ns],
            Open=[100.0], High=[105.0], Low=[99.0], Close=[103.0], Volume=[1000],
        )

        result = _from_sinopac_kbar(fake_kbar)

        expected_dt = datetime.fromtimestamp(raw_ns / 1_000_000_000 - 8 * 3600)
        assert len(result) == 1
        assert result[0].timestamp == expected_dt

    def test_ohlcv_values_preserved(self):
        """Open/High/Low/Close/Volume must survive the conversion unchanged."""
        fake_kbar = types.SimpleNamespace(
            ts=[0],
            Open=[111.0], High=[222.0], Low=[99.5], Close=[200.0], Volume=[9999],
        )

        result = _from_sinopac_kbar(fake_kbar)

        assert result[0].open  == 111.0
        assert result[0].high  == 222.0
        assert result[0].low   == 99.5
        assert result[0].close == 200.0
        assert result[0].volume == 9999


# ── SinopacBrokerAPI: guard-clause tests ─────────────────────────────────────

class TestNotConnectedGuards:
    """Methods that require a connection must raise ConnectionError immediately."""

    def test_get_positions_raises_when_not_connected(self, broker):
        broker._connected = False
        with pytest.raises(ConnectionError):
            broker.get_positions()

    def test_get_balance_raises_when_not_connected(self, broker):
        broker._connected = False
        with pytest.raises(ConnectionError):
            broker.get_balance()


# ── SinopacBrokerAPI: place_order exception path ─────────────────────────────

class TestPlaceOrder:
    def test_shioaji_exception_returns_rejected_result(self, broker, sample_order):
        """Any exception from the Shioaji layer must be caught and returned as REJECTED."""
        broker.api.place_order.side_effect = RuntimeError("Shioaji connection dropped")

        result = broker.place_order(sample_order)

        assert isinstance(result, OrderResult)
        assert result.status == OrderStatus.REJECTED
        assert "Order failed" in result.message
