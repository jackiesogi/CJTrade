"""AccountClient keeps accounts and orders; prices come from client.market."""
from __future__ import annotations

from datetime import datetime

from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.marketdata import Capabilities
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata.arenax import ArenaXMarketData
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.product import Product


class OneBar(MarketData):
    name = "one-bar"

    def __init__(self):
        self.asked = []

    @property
    def capabilities(self):
        return Capabilities(intervals=frozenset({"1d"}), snapshots=True)

    def get_kbars(self, symbol, start, end, interval="1d"):
        self.asked.append((symbol, start, end, interval))
        return [Kbar(datetime(2026, 3, 2, 9), 1, 1, 1, 1, 1, symbol)]

    def get_snapshots(self, symbols):
        return [f"snap:{s}" for s in symbols]


def test_without_a_market_the_broker_provides_one():
    client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
    assert isinstance(client.market, ArenaXMarketData)
    assert client.market.broker is client.broker_api


def test_a_given_market_answers_the_price_calls():
    market = OneBar()
    client = AccountClient(BrokerType.ARENAX, market=market, api_key="testkey123")
    assert client.market is market
    bars = client.get_kbars(Product("2330"), "2026-03-02", "2026-03-03", "1d")
    assert market.asked == [("2330", "2026-03-02", "2026-03-03", "1d")]
    assert bars[0].symbol == "2330"
    assert client.get_snapshots([Product("2330")]) == ["snap:2330"]


def test_a_broker_that_only_takes_orders_needs_no_price_methods():
    """The order-only broker case: implement the abstract methods, nothing
    about prices, and it can be constructed."""
    import pytest
    from cjtrade.pkgs.brokers.base_broker_api import BrokerAPIBase
    stubs = {name: (lambda self, *a, **k: None)
             for name in BrokerAPIBase.__abstractmethods__}
    OrdersOnly = type("OrdersOnly", (BrokerAPIBase,), stubs)
    broker = OrdersOnly()
    assert broker.market_data() is None
    with pytest.raises(NotImplementedError):
        broker.get_kbars(Product("2330"), "2026-03-02", "2026-03-03", "1d")
    assert not {"get_kbars", "get_snapshots", "get_bid_ask"} & BrokerAPIBase.__abstractmethods__
