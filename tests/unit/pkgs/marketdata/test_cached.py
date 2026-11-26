"""Cached only fetches what the price cache lacks, and only records what it got.

Ported from tests/unit/apps/arenax/test_kbar_coverage.py, which pinned the
same rules on ArenaX_BackendBase.kbars before the cache moved here.

A window is "covered" only once bars for it exist. Coverage is what decides
whether the source is asked at all, so a window recorded as covered when
nothing came back is never fetched again. Found in a live cache: 2317's 1m
coverage claimed 2023-01-16 -> 2027-08-18 while its last real bar was
2026-11-09, and a request inside that span returned zero bars.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.db.db_api import compute_missing_ranges
from cjtrade.pkgs.db.db_api import get_coverage_ranges
from cjtrade.pkgs.marketdata import Cached
from cjtrade.pkgs.marketdata import MarketDataUnavailable
from cjtrade.pkgs.marketdata import UnsupportedRequest

from .conftest import FakeSource
from .conftest import minute_bars
from .conftest import SYM


def coverage(cache):
    return get_coverage_ranges(cache.conn, SYM, "1m")


def day_window(day):
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def test_a_fetch_that_returns_nothing_records_no_coverage(cache):
    day = (datetime.now() - timedelta(days=20)).date()
    Cached(FakeSource(responses=[[]]), cache).get_kbars(SYM, *day_window(day), "1m")
    assert coverage(cache) == []


def test_an_empty_fetch_leaves_the_window_retryable(cache):
    day = (datetime.now() - timedelta(days=20)).date()
    source = FakeSource(responses=[[], minute_bars(day, 4)])
    market = Cached(source, cache)
    market.get_kbars(SYM, *day_window(day), "1m")
    second = market.get_kbars(SYM, *day_window(day), "1m")
    assert len(source.calls) == 2
    assert len(second) == 4


def test_coverage_never_reaches_into_the_future(cache):
    today = datetime.now()
    served = minute_bars((today - timedelta(days=3)).date(), 6)
    Cached(FakeSource(served), cache).get_kbars(
        SYM, today - timedelta(days=5), today + timedelta(days=400), "1m")
    assert coverage(cache)
    assert max(e for _, e in coverage(cache)) <= int(today.timestamp()) + 5


def test_the_future_is_still_a_gap(cache):
    today = datetime.now()
    served = minute_bars((today - timedelta(days=3)).date(), 6)
    Cached(FakeSource(served), cache).get_kbars(
        SYM, today - timedelta(days=5), today + timedelta(days=400), "1m")
    assert compute_missing_ranges(cache.conn, SYM, "1m",
                                  int((today + timedelta(days=100)).timestamp()),
                                  int((today + timedelta(days=300)).timestamp()))


def test_a_whole_past_day_is_fetched_once(cache):
    """Coverage spans the requested window, not the bars' own span: bars exist
    only 09:01-13:30, so narrowing it would re-fetch every day's margins."""
    day = (datetime.now() - timedelta(days=30)).date()
    source = FakeSource(minute_bars(day, 5))
    market = Cached(source, cache)
    market.get_kbars(SYM, *day_window(day), "1m")
    market.get_kbars(SYM, *day_window(day), "1m")
    assert len(source.calls) == 1


def test_a_cached_window_is_served_without_the_source(cache):
    day = datetime(2026, 3, 2).date()
    source = FakeSource(minute_bars(day, 5))
    market = Cached(source, cache)
    first = market.get_kbars(SYM, *day_window(day), "1m")
    second = market.get_kbars(SYM, *day_window(day), "1m")
    assert len(first) == len(second) == 5
    assert len(source.calls) == 1


def test_a_long_gap_is_fetched_in_chunks_and_only_answered_chunks_are_recorded(cache):
    """A source that only has the recent part of a long window (yfinance keeps
    about 30 days of 1m bars) must not get the whole window marked fetched."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    recent = minute_bars((today - timedelta(days=2)).date(), 3)
    source = FakeSource(recent)
    Cached(source, cache).get_kbars(SYM, today - timedelta(days=120), today, "1m")
    assert len(source.calls) >= 4
    (start, _), = coverage(cache)
    assert start >= int((today - timedelta(days=31)).timestamp())


def test_stored_bars_are_never_overwritten(cache):
    day = datetime(2026, 3, 2).date()
    Cached(FakeSource(minute_bars(day, 3, base=100.0)), cache).get_kbars(
        SYM, *day_window(day), "1m")
    cache.store(SYM, "1m", minute_bars(day, 3, base=999.0), "fake")
    assert [k.close for k in cache.get_kbars(SYM, *day_window(day), "1m")] == [100, 101, 102]


def test_a_failed_chunk_stays_a_gap(cache):
    day = datetime(2026, 3, 2).date()
    Cached(FakeSource(fail=MarketDataUnavailable("down")), cache).get_kbars(
        SYM, *day_window(day), "1m")
    assert coverage(cache) == []


def test_an_unsupported_interval_is_not_swallowed(cache):
    with pytest.raises(UnsupportedRequest):
        Cached(FakeSource(intervals=("1d",)), cache).get_kbars(
            SYM, "2026-03-02", "2026-03-03", "1m")


def test_the_window_is_half_open(cache):
    day = datetime(2026, 3, 2).date()
    bars = Cached(FakeSource(minute_bars(day, 5)), cache).get_kbars(
        SYM, datetime(2026, 3, 2, 9, 2), datetime(2026, 3, 2, 9, 4), "1m")
    assert [k.timestamp.minute for k in bars] == [2, 3]
