"""Fallback picks the first source that can answer; aggregate builds bars."""
from __future__ import annotations

from datetime import datetime

import pytest
from cjtrade.pkgs.marketdata import aggregate
from cjtrade.pkgs.marketdata import Fallback
from cjtrade.pkgs.marketdata import MarketDataUnavailable
from cjtrade.pkgs.marketdata import UnsupportedRequest
from cjtrade.pkgs.marketdata.base import to_datetime

from .conftest import FakeSource
from .conftest import minute_bars
from .conftest import SYM

DAY = datetime(2026, 3, 2).date()


class TestFallback:
    def test_the_first_non_empty_answer_wins(self):
        a = FakeSource(name="a", responses=[[]])
        b = FakeSource(minute_bars(DAY, 3), name="b")
        market = Fallback([a, b])
        assert len(market.get_kbars(SYM, "2026-03-02", "2026-03-03", "1m")) == 3
        assert market.last_source == "b"

    def test_a_source_without_the_interval_is_not_asked(self):
        daily_only = FakeSource(name="daily", intervals=("1d",))
        minute = FakeSource(minute_bars(DAY, 2), name="minute")
        Fallback([daily_only, minute]).get_kbars(SYM, "2026-03-02", "2026-03-03", "1m")
        assert daily_only.calls == []

    def test_a_failing_source_is_skipped(self):
        broken = FakeSource(name="broken", fail=MarketDataUnavailable("down"))
        ok = FakeSource(minute_bars(DAY, 2), name="ok")
        assert len(Fallback([broken, ok]).get_kbars(SYM, "2026-03-02", "2026-03-03")) == 2

    def test_a_source_that_turns_out_unsupported_is_skipped(self):
        gated = FakeSource(name="gated", fail=UnsupportedRequest("plan"))
        ok = FakeSource(minute_bars(DAY, 2), name="ok")
        assert len(Fallback([gated, ok]).get_kbars(SYM, "2026-03-02", "2026-03-03")) == 2

    def test_an_interval_no_source_serves_is_unsupported(self):
        with pytest.raises(UnsupportedRequest):
            Fallback([FakeSource(intervals=("1m",))]).get_kbars(SYM, "2026-03-02", "2026-03-03", "1d")

    def test_capabilities_are_the_union(self):
        market = Fallback([FakeSource(intervals=("1d",)),
                           FakeSource(intervals=("1m",), snapshots=[])])
        assert market.capabilities.intervals == {"1m", "1d"}
        assert market.capabilities.snapshots

    def test_snapshots_come_from_the_source_that_has_them(self):
        market = Fallback([FakeSource(), FakeSource(snapshots=["snap"])])
        assert market.get_snapshots([SYM]) == ["snap"]


class TestAggregate:
    def test_five_minute_bars_are_stamped_at_their_close(self):
        bars = aggregate(minute_bars(DAY, 10), "5m")
        assert [b.timestamp.strftime("%H:%M") for b in bars] == ["09:05", "09:10"]
        assert bars[0].open == 100 and bars[0].close == 104 and bars[0].volume == 50

    def test_the_last_hour_of_a_session_ends_at_13_30(self):
        bars = aggregate(minute_bars(DAY, 30, start=(13, 1)), "1h")
        assert [b.timestamp.strftime("%H:%M") for b in bars] == ["13:30"]

    def test_a_day_is_stamped_at_09_00(self):
        (bar,) = aggregate(minute_bars(DAY, 270), "1d")
        assert bar.timestamp == datetime(2026, 3, 2, 9, 0)
        assert bar.high == max(k.high for k in minute_bars(DAY, 270))

    def test_an_unknown_interval_is_refused(self):
        with pytest.raises(ValueError):
            aggregate(minute_bars(DAY, 3), "7m")


def test_a_date_means_midnight():
    assert to_datetime("2026-03-02") == datetime(2026, 3, 2)
    assert to_datetime(DAY) == datetime(2026, 3, 2)
