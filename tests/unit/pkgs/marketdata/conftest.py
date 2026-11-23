"""Shared fakes for the market data tests. Nothing here reaches the network."""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.marketdata import Capabilities
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata import PriceCache
from cjtrade.pkgs.marketdata import UnsupportedRequest
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar

SYM = "2317"


def minute_bars(day, count=5, base=100.0, symbol=SYM, start=(9, 1)):
    """`count` 1m bars on `day`, stamped at their close from 09:01."""
    first = datetime(day.year, day.month, day.day, *start)
    return [Kbar(first + timedelta(minutes=i), base, base + 1, base - 1,
                 base + i, 10, symbol) for i in range(count)]


class FakeSource(MarketData):
    """Serves exactly the bars a test gives it, and records every request.

    `responses`, when given, is consumed one list per request instead.
    """

    def __init__(self, bars=(), intervals=("1m",), name="fake", responses=None,
                 fail=None, snapshots=None):
        self._bars = list(bars)
        self._intervals = frozenset(intervals)
        self.name = name
        self._responses = None if responses is None else list(responses)
        self._fail = fail
        self._snapshots = snapshots
        self.calls = []

    @property
    def capabilities(self):
        return Capabilities(intervals=self._intervals,
                            snapshots=self._snapshots is not None)

    def get_kbars(self, symbol, start, end, interval="1m"):
        self.require_interval(interval)
        start, end = to_window(start, end)
        self.calls.append((symbol, start, end, interval))
        if self._fail is not None:
            raise self._fail
        if self._responses is not None:
            return self._responses.pop(0) if self._responses else []
        return in_window([b for b in self._bars if b.symbol == symbol], start, end)

    def get_snapshots(self, symbols):
        if self._snapshots is None:
            raise UnsupportedRequest("no snapshots")
        return self._snapshots


@pytest.fixture
def cache(tmp_path):
    c = PriceCache(str(tmp_path / "price.db"))
    yield c
    c.close()
