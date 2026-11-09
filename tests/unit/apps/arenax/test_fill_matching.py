"""Unit tests for ArenaX fill matching — bar lookup by timestamp, not by offset."""
from datetime import datetime
from datetime import timedelta

import pandas as pd
import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.pkgs.models.order import OrderAction


# ── Stub market ───────────────────────────────────────────────────────────────

class _StubMarket:
    """Only what _find_fill_time reads: historical_data and start_date."""

    def __init__(self, bars: dict):
        self.historical_data = {}
        self.start_date = None
        for symbol, rows in bars.items():
            index = pd.DatetimeIndex([ts for ts, _ in rows])
            df = pd.DataFrame({"Close": [c for _, c in rows]}, index=index)
            self.historical_data[symbol] = {"data": df, "timestamps": index.to_numpy()}
            if self.start_date is None:
                self.start_date = index[0].to_pydatetime()


def _backend(bars: dict) -> ArenaX_BackendBase:
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)   # no __init__: no disk, no network
    b.market = _StubMarket(bars)
    return b


def _session(day: datetime, closes: list) -> list:
    """One trading day's bars starting 09:00, one per minute."""
    return [(day.replace(hour=9, minute=0) + timedelta(minutes=i), c)
            for i, c in enumerate(closes)]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFindFillTime:
    def test_returns_matching_bar_timestamp(self):
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [100.0, 99.0, 98.0, 97.0])})
        got = b._find_fill_time("2317", day.replace(hour=9, minute=0),
                                day.replace(hour=9, minute=3), OrderAction.BUY, 98.0)
        assert got == day.replace(hour=9, minute=2)

    def test_returns_none_when_no_bar_matches(self):
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [100.0, 101.0, 102.0])})
        assert b._find_fill_time("2317", day.replace(hour=9, minute=0),
                                 day.replace(hour=9, minute=2), OrderAction.BUY, 50.0) is None

    def test_range_is_exclusive_at_start_inclusive_at_end(self):
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [10.0, 20.0, 30.0])})
        # 09:00 holds the only match but is excluded — it was checked last pass.
        assert b._find_fill_time("2317", day.replace(hour=9, minute=0),
                                 day.replace(hour=9, minute=2), OrderAction.BUY, 10.0) is None
        # 09:02 is the end of the range and is included.
        assert b._find_fill_time("2317", day.replace(hour=9, minute=0),
                                 day.replace(hour=9, minute=2),
                                 OrderAction.SELL, 30.0) == day.replace(hour=9, minute=2)

    def test_second_day_matches_second_day_prices(self):
        """The old uniform-grid offset drifted ~1170 minutes per day."""
        d1, d2 = datetime(2025, 9, 1), datetime(2025, 9, 2)
        bars = _session(d1, [100.0] * 270) + _session(d2, [50.0] * 270)
        b = _backend({"2317": bars})
        # Only day 2 trades at 50. Asking over day 2 must find it there.
        got = b._find_fill_time("2317", d2.replace(hour=9, minute=0),
                                d2.replace(hour=13, minute=0), OrderAction.BUY, 60.0)
        assert got is not None
        assert got.date() == d2.date()
        # And asking over day 1 must find nothing.
        assert b._find_fill_time("2317", d1.replace(hour=9, minute=0),
                                 d1.replace(hour=13, minute=0),
                                 OrderAction.BUY, 60.0) is None

    def test_does_not_wrap_past_the_last_bar(self):
        """`idx = minute % n` used to wrap round to bar 0 and match again."""
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [10.0, 99.0, 99.0])})
        # Range runs far beyond the last bar; the 10.0 at 09:00 must not reappear.
        assert b._find_fill_time("2317", day.replace(hour=9, minute=2),
                                 day.replace(hour=23, minute=0),
                                 OrderAction.BUY, 10.0) is None

    def test_unknown_symbol_and_empty_data(self):
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [10.0])})
        assert b._find_fill_time("9999", day, day + timedelta(hours=1),
                                 OrderAction.BUY, 1e12) is None
        b.market.historical_data["empty"] = {"data": pd.DataFrame(), "timestamps": None}
        assert b._find_fill_time("empty", day, day + timedelta(hours=1),
                                 OrderAction.BUY, 1e12) is None

    def test_lowercase_close_column(self):
        day = datetime(2025, 9, 1)
        b = _backend({"2317": _session(day, [10.0, 20.0])})
        info = b.market.historical_data["2317"]
        info["data"] = info["data"].rename(columns={"Close": "close"})
        assert b._find_fill_time("2317", day.replace(hour=9, minute=0),
                                 day.replace(hour=9, minute=1),
                                 OrderAction.SELL, 20.0) == day.replace(hour=9, minute=1)


if __name__ == "__main__":
    pytest.main([__file__])
