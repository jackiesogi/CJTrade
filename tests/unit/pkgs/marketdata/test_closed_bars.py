"""Only closed bars are returned, the same way by every source, and offline
means offline. Nothing here reaches the network."""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.apps.ArenaX.demo_backend import ArenaX_Backend_None
from cjtrade.pkgs.marketdata import aggregate
from cjtrade.pkgs.marketdata import bars_from_ticks
from cjtrade.pkgs.marketdata import Cached
from cjtrade.pkgs.marketdata import FinMindMarketData
from cjtrade.pkgs.marketdata import from_names
from cjtrade.pkgs.marketdata import MarketDataUnavailable
from cjtrade.pkgs.marketdata import OfflineMarketData
from cjtrade.pkgs.marketdata import YFinanceMarketData
from cjtrade.pkgs.marketdata.base import closed
from cjtrade.pkgs.marketdata.base import closed_until
from cjtrade.pkgs.marketdata.sinopac import SinopacMarketData
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.tick import Tick

from .conftest import FakeSource
from .conftest import minute_bars

DAY = datetime(2026, 3, 2)          # a Monday
NOW = datetime(2026, 3, 2, 10, 2, 30)


def full_day(symbol="2330"):
    """09:01 .. 13:30, one bar a minute, as Shioaji and the cache hold them."""
    return minute_bars(DAY, count=270, symbol=symbol)


class SessionBroker:
    """A Sinopac broker mid-session: it hands out the minute still trading too."""

    def __init__(self, bars, now):
        self.bars, self.now = bars, now

    def get_kbars(self, product, start, end, interval):
        forming = self.now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return [b for b in self.bars if b.timestamp <= forming]


def sinopac_at(now, bars):
    source = SinopacMarketData(SessionBroker(bars, now))
    source.now = lambda: now
    return source


# ── the rule itself ──────────────────────────────────────────────────────────

def test_a_daily_bar_is_open_until_1330():
    bar = Kbar(DAY.replace(hour=9), 1, 1, 1, 1, 1, "2330")
    assert closed([bar], "1d", DAY.replace(hour=13, minute=29)) == []
    assert closed([bar], "1d", DAY.replace(hour=13, minute=30)) == [bar]
    assert closed_until("1d", DAY.replace(hour=10)) == DAY
    assert closed_until("1d", DAY.replace(hour=14)) == DAY + timedelta(days=1)
    assert closed_until("1m", NOW) == NOW


def test_ticks_become_1m_bars_stamped_at_their_close():
    t = lambda h, m, s, p, v=1: Tick(DAY.replace(hour=h, minute=m, second=s), p, v, "2330")  # noqa: E731
    bars = bars_from_ticks([t(9, 0, 5, 100), t(9, 0, 50, 102), t(9, 0, 30, 99),
                            t(9, 3, 0, 101, 5), t(13, 29, 59, 103), t(13, 30, 0, 104, 9)])
    assert [b.timestamp.strftime("%H:%M") for b in bars] == ["09:01", "09:04", "13:30"]
    first = bars[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (100, 102, 99, 102, 3)
    assert bars[-1].close == 104 and bars[-1].volume == 10, "the 13:30 auction joins the 13:30 bar"


# ── Sinopac drops the minute still trading ───────────────────────────────────

def test_sinopac_leaves_out_the_minute_still_trading():
    out = sinopac_at(NOW, full_day()).get_kbars("2330", DAY, DAY + timedelta(days=1), "1m")
    assert out[-1].timestamp == DAY.replace(hour=10, minute=2)


def test_sinopac_builds_coarser_bars_only_once_they_close():
    out = sinopac_at(NOW, full_day()).get_kbars("2330", DAY, DAY + timedelta(days=1), "5m")
    assert out[-1].timestamp == DAY.replace(hour=10, minute=0)
    daily = sinopac_at(NOW, full_day()).get_kbars("2330", DAY, DAY + timedelta(days=1), "1d")
    assert daily == []


# ── ArenaX and Sinopac agree ─────────────────────────────────────────────────

@pytest.fixture
def arenax_at(tmp_path, monkeypatch):
    """An ArenaX backend serving `bars` whose simulated clock reads `now`."""
    monkeypatch.setattr(ArenaX_Backend_None, "_initialize_market_time", lambda self: None)

    def make(now, bars, interval="1m"):
        backend = ArenaX_Backend_None(market_data=FakeSource(bars, intervals=(interval,)),
                                      price_db_path=str(tmp_path / "p.db"),
                                      state_dir=str(tmp_path))
        backend.market.set_historical_time_abs(real_init_time=datetime.now(),
                                               mock_init_time=now)
        backend.market.set_market_time(now)
        return backend
    return make


@pytest.mark.parametrize("now", [NOW, DAY.replace(hour=13, minute=29, second=59),
                                 DAY.replace(hour=15)])
@pytest.mark.parametrize("interval", ["1m", "5m", "1h", "1d"])
def test_arenax_and_sinopac_return_the_same_bars_at_the_same_moment(arenax_at, now, interval):
    minutes = full_day()
    # ArenaX's cache holds every bar of the day; its clock decides what is seen.
    backend = arenax_at(now, aggregate(minutes, interval), interval)
    from_arenax = backend.kbars("2330", DAY.isoformat(), (DAY + timedelta(days=1)).isoformat(),
                                interval)
    from_sinopac = sinopac_at(now, minutes).get_kbars("2330", DAY, DAY + timedelta(days=1),
                                                      interval)
    # Before 13:30 the day's bar is still open, so neither shows it.
    assert bool(from_sinopac) == (interval != "1d" or now.hour >= 14)
    assert [(b.timestamp, b.close, b.volume) for b in from_arenax] == \
        [(b.timestamp, b.close, b.volume) for b in from_sinopac]


def test_the_arenax_route_still_takes_whole_dates_with_an_inclusive_end(arenax_at):
    backend = arenax_at(DAY.replace(hour=15), full_day())
    assert len(backend.kbars("2330", "2026-03-02", "2026-03-02", "1m")) == 270


# ── offline ──────────────────────────────────────────────────────────────────

def test_offline_switch_stops_network_sources(monkeypatch):
    monkeypatch.setenv("CJTRADE_OFFLINE", "1")
    import requests
    import yfinance

    def boom(*a, **k):
        raise AssertionError("went to the network")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(yfinance, "download", boom)
    for source in (FinMindMarketData(token="t"), YFinanceMarketData()):
        with pytest.raises(MarketDataUnavailable, match="CJTRADE_OFFLINE"):
            source.get_kbars("2330", DAY, DAY + timedelta(days=1), "1d")


def test_offline_serves_only_what_the_cache_holds(cache):
    stored = minute_bars(DAY, count=5, symbol="2330")
    cache.store("2330", "1m", stored, "preload")
    market = Cached(OfflineMarketData(), cache)
    got = market.get_kbars("2330", DAY, DAY + timedelta(days=2), "1m")
    assert [(b.timestamp, b.close) for b in got] == [(b.timestamp, b.close) for b in stored]
    assert market.get_kbars("2317", DAY, DAY + timedelta(days=2), "1m") == []


def test_offline_by_name_reads_the_given_file(cache):
    cache.store("2330", "1d", [Kbar(DAY.replace(hour=9), 1, 2, 0, 1, 3, "2330")], "preload")
    market = from_names("offline", cache_path=cache.path)
    assert market.source.name == "offline"
    assert len(market.get_kbars("2330", DAY, DAY + timedelta(days=1), "1d")) == 1


def test_cache_source_uses_the_given_file(cache):
    market = from_names("cache", cache=False, cache_path=cache.path)
    assert market.path == cache.path


def test_a_daily_window_is_not_marked_fetched_before_the_close(cache, monkeypatch):
    import cjtrade.pkgs.marketdata.cache as cache_mod

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return DAY.replace(hour=10)
    monkeypatch.setattr(cache_mod, "datetime", Clock)
    cache.mark_fetched("2330", "1d", DAY - timedelta(days=3), DAY + timedelta(days=1), "x")
    assert cache.missing("2330", "1d", DAY - timedelta(days=3), DAY + timedelta(days=1)) == \
        [(DAY, DAY + timedelta(days=1))]
