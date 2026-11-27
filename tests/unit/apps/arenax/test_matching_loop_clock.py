"""The matching loop waits for a clock instead of dying without one.

A backtest server whose random start found no prices has no market time
until the client sets one. The loop used to call get_market_time() anyway,
raise a TypeError, and leave the server running with no matching thread.
"""
import threading
from datetime import datetime

from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer
from cjtrade.apps.ArenaX.market_data import ArenaX_Market
from cjtrade.pkgs.marketdata import OfflineMarketData


class _Backend:
    def __init__(self, market):
        self.market = market
        self.sweeps = 0

    def expire_resting_orders(self):
        self.market.get_market_time()     # raises while the clock is unset
        self.sweeps += 1


def _server(backend):
    srv = ArenaX_BrokerSideServer.__new__(ArenaX_BrokerSideServer)
    srv.backend = backend
    srv._backend_lock = threading.RLock()
    srv._stop_event = threading.Event()
    srv._match_interval = 0.01
    srv._skip_non_trading_hours = False
    return srv


def _market(tmp_path):
    return ArenaX_Market(market_data=OfflineMarketData(),
                         price_db_path=str(tmp_path / "price.db"))


def test_a_new_market_has_no_clock(tmp_path):
    assert not _market(tmp_path).clock_started


def test_setting_a_start_time_starts_the_clock(tmp_path):
    market = _market(tmp_path)
    market.set_historical_time_abs(datetime.now(), datetime(2024, 4, 29))
    assert market.clock_started


def test_the_loop_survives_until_the_clock_is_set(tmp_path):
    backend = _Backend(_market(tmp_path))
    srv = _server(backend)
    loop = threading.Thread(target=srv._matching_loop, daemon=True)
    loop.start()
    srv._stop_event.wait(0.1)
    assert loop.is_alive() and backend.sweeps == 0

    backend.market.set_historical_time_abs(datetime.now(), datetime(2024, 4, 29))
    srv._stop_event.wait(0.1)
    srv._stop_event.set()
    loop.join(timeout=2)
    assert backend.sweeps > 0
