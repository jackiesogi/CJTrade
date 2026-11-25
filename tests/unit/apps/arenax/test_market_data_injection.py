"""ArenaX simulates against whatever MarketData it is given.

The historical backend used to refuse to start without a Sinopac account,
which it needed only to read prices. It now needs a source of 1m bars, and
nothing else.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.apps.ArenaX.backtest_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer
from cjtrade.apps.ArenaX.demo_backend import ArenaX_Backend_None
from cjtrade.pkgs.marketdata import Capabilities
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar

START = datetime(2025, 9, 1, 9, 0)


class Bars(MarketData):
    """One trading week of 1m bars for any symbol, rising by 0.5 a bar."""

    name = "bars"

    def __init__(self, intervals=("1m", "1d")):
        self._intervals = frozenset(intervals)
        self.asked = []

    @property
    def capabilities(self):
        return Capabilities(intervals=self._intervals)

    def get_kbars(self, symbol, start, end, interval="1m"):
        self.require_interval(interval)
        start, end = to_window(start, end)
        self.asked.append((symbol, start, end, interval))
        bars = []
        for d in range(5):
            day = START + timedelta(days=d)
            for m in range(1, 271):
                price = 100 + 0.5 * m
                bars.append(Kbar(day + timedelta(minutes=m), price, price, price, price, 1, symbol))
        return in_window(bars, start, end)


@pytest.fixture
def backend_kwargs(tmp_path):
    return dict(price_db_path=str(tmp_path / "price.db"), state_dir=str(tmp_path),
                num_days_preload=3)


def test_the_historical_backend_starts_without_a_broker_account(backend_kwargs):
    source = Bars()
    backend = ArenaX_Backend_Historical(market_data=source, backtest_start_date=START,
                                        **backend_kwargs)
    assert backend.real_account is None
    backend.market.create_historical_market("2330", 3)
    assert len(backend.market.historical_data["2330"]["data"]) == 3 * 270
    assert source.asked[0][3] == "1m"


def test_a_source_without_minute_bars_cannot_drive_a_replay(backend_kwargs):
    with pytest.raises(ValueError, match="1m"):
        ArenaX_Backend_Historical(market_data=Bars(intervals=("1d",)),
                                  backtest_start_date=START, **backend_kwargs)


def test_kbars_are_served_through_the_price_cache(backend_kwargs):
    source = Bars()
    backend = ArenaX_Backend_None(market_data=source, **backend_kwargs)
    first = backend.kbars("2330", "2025-09-01", "2025-09-01", "1m")
    again = backend.kbars("2330", "2025-09-01", "2025-09-01", "1m")
    assert len(first) == len(again) == 270, "end date is inclusive, as the route has it"
    assert sum(1 for a in source.asked if a[1].date() == START.date()) == 1


def test_the_server_takes_a_market_data_and_logs_in_to_nobody(tmp_path, monkeypatch):
    monkeypatch.setattr(ArenaX_Backend_None, "_initialize_market_time", lambda self: None)
    server = ArenaX_BrokerSideServer(backend_str="demo", market_data=Bars(),
                                     price_db_path=str(tmp_path / "price.db"))
    assert server.real is None
    assert server.backend.market_data.name == "bars"


def test_an_order_loads_its_symbols_bars_without_a_snapshot_first(backend_kwargs):
    """Orders are matched against the replay bars, so placing one must load
    them. They used to be loaded only by snapshot(), and a client that reads
    kbars instead placed orders that could never fill."""
    from cjtrade.pkgs.models.order import Order
    from cjtrade.pkgs.models.order import OrderAction
    from cjtrade.pkgs.models.order import OrderLot
    from cjtrade.pkgs.models.order import OrderType
    from cjtrade.pkgs.models.order import PriceType
    from cjtrade.pkgs.models.product import Product

    backend = ArenaX_Backend_Historical(market_data=Bars(), backtest_start_date=START,
                                        initial_balance=1_000_000, **backend_kwargs)
    backend.login()
    assert "2330" not in backend.market.historical_data
    backend.place_order(Order(
        product=Product(symbol="2330"), action=OrderAction.BUY, price=101.0,
        quantity=1, price_type=PriceType.LMT, order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd))
    assert len(backend.market.historical_data["2330"]["data"]) == 3 * 270, \
        "num_days_preload days, with or without a broker account"
