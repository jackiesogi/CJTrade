"""
tests/unit/apps/arenax/test_kbar_coverage.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A range is only "covered" once bars for it actually exist.

`ArenaX_BackendBase.kbars()` records coverage after fetching gaps from the
broker, and coverage is what `compute_missing_ranges` consults to decide
whether to ask the broker at all. So a range recorded as covered when nothing
came back is permanent: every later run sees no gap, skips the broker, and
returns whatever truncated set is already cached. Nothing reports it.

Found in the live cache rather than theorised. 2317's 1m coverage claimed
2023-01-16 → 2027-08-18 while its last real bar was 2026-11-09 -- 282 days of
phantom coverage -- and a request for 2026-12-01 → 2027-06-01 duly reported
zero gaps and returned zero bars.

`market_data._persist_kbars` already did this correctly (early return on an
empty fetch, coverage from min/max of the bars); this call site was the
outlier, and these tests pin both halves of the rule.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.apps.ArenaX.price_db import ArenaX_LocalPriceDB
from cjtrade.pkgs.models.kbar import Kbar

SYM = "2317"


# ══════════════════════════════════════════════════════════════════════════
#  Fixtures: a real price DB and a broker we control
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def price_db(tmp_path):
    db = ArenaX_LocalPriceDB(str(tmp_path / "price.db"))
    yield db
    try:
        db.conn.close()
    except Exception:
        pass


def bars(day, count=5, base=100.0, start_hour=9):
    """`count` 1m bars on one day."""
    return [Kbar(timestamp=datetime(day.year, day.month, day.day,
                                    start_hour, 1) + timedelta(minutes=i),
                 open=base, high=base, low=base, close=base + i,
                 volume=100, symbol=SYM)
            for i in range(count)]


class FakeBroker:
    """Stands in for `real_account`, returning exactly what a test dictates."""

    def __init__(self, responses):
        # responses: list of Kbar lists, consumed one per chunk request
        self._responses = list(responses)
        self.calls = []

    def is_connected(self):
        return True

    def connect(self):
        return True

    def get_kbars(self, start, end, product, interval="1m"):
        self.calls.append((start, end, interval))
        return self._responses.pop(0) if self._responses else []


class Backend:
    """`kbars()` lifted off ArenaX_BackendBase with only what it touches.

    Composed rather than subclassed because constructing a real backend starts
    a market clock and a Sinopac login; `kbars()` itself reaches for exactly
    three attributes, all provided here.
    """

    def __init__(self, price_db, broker):
        from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
        self.kbars = ArenaX_BackendBase.kbars.__get__(self)
        self.real_account = broker
        self.yf_calls = []

        class _Market:
            pass
        self.market = _Market()
        self.market.price_db = price_db

    def kbars_yf(self, symbol, start, end, interval="1m"):
        """Stubbed: the real one reaches the network. kbars() falls back to it
        whenever nothing else produced bars, and it writes no coverage of its
        own, so returning nothing keeps these tests about the broker path."""
        self.yf_calls.append((symbol, start, end, interval))
        return []


def coverage(db, symbol=SYM, timeframe="1m"):
    from cjtrade.pkgs.db.db_api import get_coverage_ranges
    return get_coverage_ranges(db.conn, symbol, timeframe)


def gaps(db, start, end, symbol=SYM, timeframe="1m"):
    return db.get_missing_ranges(symbol, timeframe, start, end) \
        if hasattr(db, "get_missing_ranges") else None


# ══════════════════════════════════════════════════════════════════════════
#  An empty fetch must not claim the range
# ══════════════════════════════════════════════════════════════════════════

def test_a_fetch_that_returns_nothing_records_no_coverage(price_db):
    """The regression test. A window whose data does not exist yet has to stay
    a gap, or it can never be fetched once it does exist.

    yfinance is the final fallback when nothing else produced bars, so this
    asserts on the coverage table rather than on the returned list -- the
    point is what was written, not what came back.
    """
    day = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    backend = Backend(price_db, FakeBroker([[]]))
    backend.kbars(SYM, day, day, "1m")
    assert coverage(price_db) == [], \
        "an empty fetch claimed the range as covered"


def test_an_empty_fetch_leaves_the_range_retryable(price_db):
    """The consequence that matters: asking again still asks the broker."""
    day_dt = datetime.now() - timedelta(days=20)
    day = day_dt.strftime("%Y-%m-%d")
    broker = FakeBroker([[], bars(day_dt.date(), 4)])
    backend = Backend(price_db, broker)

    backend.kbars(SYM, day, day, "1m")
    assert coverage(price_db) == []
    # The data has since appeared at the broker.
    second = backend.kbars(SYM, day, day, "1m")
    assert len(broker.calls) == 2, "the second attempt never reached the broker"
    assert len(second) == 4


def test_coverage_never_reaches_into_the_future(price_db):
    """2317's actual failure: a range requested years ahead, served only up to
    the present, recorded in full. A successful fetch vouches for the past it
    returned, never for data that does not exist yet."""
    today = datetime.now()
    served = bars((today - timedelta(days=3)).date(), 6)
    far_future = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    backend = Backend(price_db, FakeBroker([served]))
    backend.kbars(SYM, (today - timedelta(days=5)).strftime("%Y-%m-%d"),
                  far_future, "1m")

    ranges = coverage(price_db)
    assert len(ranges) == 1
    _, end_ts = ranges[0]
    assert end_ts <= int(today.timestamp()) + 5, \
        "coverage was recorded for a window in the future"


def test_the_future_tail_is_still_reported_as_a_gap(price_db):
    """Having clamped the coverage, the window that has not happened yet must
    stay fetchable -- otherwise the fix trades one silent truncation for
    another, which is the whole defect."""
    today = datetime.now()
    served = bars((today - timedelta(days=3)).date(), 6)
    backend = Backend(price_db, FakeBroker([served]))
    backend.kbars(SYM, (today - timedelta(days=5)).strftime("%Y-%m-%d"),
                  (today + timedelta(days=400)).strftime("%Y-%m-%d"), "1m")

    from cjtrade.pkgs.db.db_api import compute_missing_ranges
    remaining = compute_missing_ranges(
        price_db.conn, SYM, "1m",
        int((today + timedelta(days=100)).timestamp()),
        int((today + timedelta(days=300)).timestamp()))
    assert remaining, "a window in the future is no longer reported as missing"


def test_a_whole_past_day_is_covered_by_its_trading_hours(price_db):
    """The reason coverage is not narrowed to the bars' own span: bars exist
    only 09:01-13:30, so recording min..max would leave every day's margins
    missing and re-fetch them on every run."""
    day = (datetime.now() - timedelta(days=30)).date()
    broker = FakeBroker([bars(day, 5)])
    backend = Backend(price_db, broker)
    stamp = day.strftime("%Y-%m-%d")

    backend.kbars(SYM, stamp, stamp, "1m")
    assert len(broker.calls) == 1
    backend.kbars(SYM, stamp, stamp, "1m")
    assert len(broker.calls) == 1, \
        "the margins of an already-fetched day went back to the broker"


# ══════════════════════════════════════════════════════════════════════════
#  A successful fetch still caches
# ══════════════════════════════════════════════════════════════════════════

def test_a_successful_fetch_is_cached_and_served_from_cache_next_time(price_db):
    served = bars(datetime(2026, 3, 2).date(), 5)
    broker = FakeBroker([served])
    backend = Backend(price_db, broker)

    first = backend.kbars(SYM, "2026-03-02", "2026-03-02", "1m")
    assert len(first) == 5
    assert len(broker.calls) == 1

    # Second time: fully covered, so the broker is not asked again.
    second = backend.kbars(SYM, "2026-03-02", "2026-03-02", "1m")
    assert len(second) == 5
    assert len(broker.calls) == 1, "a covered range went back to the broker"


def test_coverage_spans_the_requested_window_not_the_bars(price_db):
    """A successful fetch answers for the window that was asked about, which
    is wider than the bars because the market is shut most of the day."""
    base = datetime.now() - timedelta(days=40)
    served = bars((base + timedelta(days=1)).date(), 5)
    backend = Backend(price_db, FakeBroker([served]))
    start = base.strftime("%Y-%m-%d")
    end = (base + timedelta(days=2)).strftime("%Y-%m-%d")
    backend.kbars(SYM, start, end, "1m")

    (start_ts, end_ts), = coverage(price_db)
    assert start_ts == int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    # Past the last bar, because the request was and the broker answered it.
    assert end_ts > int(max(k.timestamp for k in served).timestamp())


def test_prices_are_appended_never_overwritten(price_db):
    """The rows themselves must be immutable: a cache that rewrites history
    makes two runs over the same window incomparable."""
    first_pass = bars(datetime(2026, 3, 2).date(), 3, base=100.0)
    backend = Backend(price_db, FakeBroker([first_pass]))
    backend.kbars(SYM, "2026-03-02", "2026-03-02", "1m")

    before = price_db.get_price(SYM, "1m", datetime(2026, 3, 2),
                                datetime(2026, 3, 2, 23, 59))
    closes_before = [k.close for k in before]

    # The same timestamps come back with different prices; they must not land.
    tampered = bars(datetime(2026, 3, 2).date(), 3, base=999.0)
    for k in tampered:
        k.close = 999.0
    price_db.insert_prices_batch(SYM, tampered, timeframe="1m",
                                 source="broker_api", overwrite=False)

    after = price_db.get_price(SYM, "1m", datetime(2026, 3, 2),
                               datetime(2026, 3, 2, 23, 59))
    assert [k.close for k in after] == closes_before
