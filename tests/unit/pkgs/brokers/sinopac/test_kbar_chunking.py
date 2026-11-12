"""
tests/unit/pkgs/brokers/sinopac/test_kbar_chunking.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Shioaji refuses a kbars request spanning more than 30 days, so the adapter
splits the range for every caller.

The splitting used to live in two of the callers instead -- ArenaX_BackendBase
.kbars with 30-day chunks and market_data._fetch_from_real_account with 28-day
ones -- while real_backend.kbars and every direct client caller passed the
range straight through. `cjtrade_shell`'s kbars command takes its range from
the user and the docstring example in pkgs/analytics/technical asks for a whole
year, so those went to the broker oversized.

These tests mock `shioaji` at the boundary: the point is the window arithmetic
and the aggregation order, neither of which needs a broker session, and
neither of which can be exercised against the real API without credentials.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.brokers.sinopac import sinopac_broker_api as mod
from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.product import Product

LIMIT = SinopacBrokerAPI._KBAR_MAX_DAYS
SYM = "2330"


class FakeShioaji:
    """Records what it was asked for and answers with one bar per day."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on          # window index that raises

    def kbars(self, contract, start, end, **kwargs):
        self.calls.append((start, end))
        if self.fail_on is not None and len(self.calls) - 1 == self.fail_on:
            raise RuntimeError("shioaji said no")
        # One 09:01 bar per calendar day in [start, end], inclusive — which is
        # how shioaji treats its own end.
        first = datetime.strptime(start, "%Y-%m-%d")
        last = datetime.strptime(end, "%Y-%m-%d")
        days = (last - first).days + 1
        return [first + timedelta(days=i, hours=9, minutes=1)
                for i in range(days)]


@pytest.fixture
def api(monkeypatch):
    """A SinopacBrokerAPI whose only live parts are get_kbars and its helpers."""
    client = SinopacBrokerAPI.__new__(SinopacBrokerAPI)
    client._connected = True
    client.api = FakeShioaji()
    monkeypatch.setattr(mod, "_to_sinopac_product", lambda api, product: product)
    monkeypatch.setattr(
        mod, "_from_sinopac_kbar",
        lambda stamps, symbol="": [
            Kbar(timestamp=ts, open=10.0, high=10.0, low=10.0, close=10.0,
                 volume=1, symbol=symbol) for ts in stamps])
    return client


def windows(api):
    """The (start, end) pairs handed to shioaji, as datetimes."""
    return [(datetime.strptime(s, "%Y-%m-%d"), datetime.strptime(e, "%Y-%m-%d"))
            for s, e in api.api.calls]


# ══════════════════════════════════════════════════════════════════════════
#  No window may exceed what shioaji accepts
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("span_days", [1, 5, 28, 29, 31, 60, 90, 365, 1000])
def test_no_window_exceeds_the_broker_limit(api, span_days):
    """The regression test, across every range an experimenter might ask for.
    A year was reachable from the shell and from the technical-analysis
    example, and 365 > 30."""
    start = datetime(2025, 1, 2)
    api.get_kbars(Product(symbol=SYM), start.strftime("%Y-%m-%d"),
                  (start + timedelta(days=span_days)).strftime("%Y-%m-%d"))
    assert api.api.calls, "no request was made at all"
    for first, last in windows(api):
        # Inclusive span, which is how shioaji reads its own start/end.
        assert (last - first).days + 1 <= 30, \
            f"window {first:%Y-%m-%d}..{last:%Y-%m-%d} is over the limit"


def test_a_short_range_is_still_a_single_request(api):
    """Splitting must not cost an extra round trip on the common case."""
    api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-01-09")
    assert len(api.api.calls) == 1


def test_the_end_date_is_converted_from_exclusive_to_inclusive(api):
    """This method documents `end` as exclusive; shioaji's is inclusive. The
    conversion has to survive the split, or every window would gain a day."""
    api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-01-09")
    assert api.api.calls == [("2025-01-02", "2025-01-08")]


def test_windows_are_contiguous_and_do_not_overlap(api):
    """An overlap duplicates bars into the price cache; a gap loses days
    silently, and the cache would then be marked as covering them."""
    api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-06-30")
    pairs = windows(api)
    assert len(pairs) > 1
    for (_, prev_end), (next_start, _) in zip(pairs, pairs[1:]):
        # shioaji's end is inclusive, so the next window starts the day after.
        assert next_start == prev_end + timedelta(days=1), \
            f"{prev_end:%Y-%m-%d} -> {next_start:%Y-%m-%d} is not contiguous"


def test_the_windows_cover_exactly_the_requested_range(api):
    start, end = "2025-01-02", "2025-06-30"
    api.get_kbars(Product(symbol=SYM), start, end)
    pairs = windows(api)
    assert pairs[0][0] == datetime.strptime(start, "%Y-%m-%d")
    # Last inclusive day is the day before the exclusive end.
    assert pairs[-1][1] == datetime.strptime(end, "%Y-%m-%d") - timedelta(days=1)


def test_every_bar_in_the_range_comes_back_once(api):
    """The split is plumbing; the caller must see the same series it would
    have got from one oversized request."""
    bars = api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-04-02")
    stamps = [b.timestamp for b in bars]
    assert len(stamps) == len(set(stamps)), "a bar was fetched twice"
    assert len(stamps) == 90                      # one per day, 2 Jan .. 1 Apr
    assert stamps == sorted(stamps), "bars are not in time order"


def test_results_are_sorted_across_window_boundaries(api):
    """Windows arrive in order here, but the contract is the ordering, so it
    is asserted rather than inherited from the fake."""
    bars = api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-05-02")
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


def test_the_symbol_is_carried_onto_every_bar(api):
    bars = api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-04-02")
    assert {b.symbol for b in bars} == {SYM}


# ══════════════════════════════════════════════════════════════════════════
#  Degenerate ranges
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("start, end", [
    ("2025-01-02", "2025-01-02"),      # same day, and end is exclusive
    ("2025-01-09", "2025-01-02"),      # backwards
])
def test_an_empty_range_asks_the_broker_nothing(api, start, end):
    assert api.get_kbars(Product(symbol=SYM), start, end) == []
    assert api.api.calls == []


def test_a_disconnected_client_refuses_before_touching_the_api(api):
    api._connected = False
    with pytest.raises(ConnectionError):
        api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-04-02")
    assert api.api.calls == []


# ══════════════════════════════════════════════════════════════════════════
#  Failure must not look like success
# ══════════════════════════════════════════════════════════════════════════

def test_a_failed_window_raises_rather_than_returning_a_partial_series(api):
    """Callers depend on the exception: ArenaX_BackendBase.kbars falls through
    to yfinance on one, and it records cache coverage for whatever it is
    handed. A silently truncated series would be written to the price cache
    and marked complete -- the same shape of bug as the coverage poisoning
    that was just fixed in base_backend."""
    api.api = FakeShioaji(fail_on=2)
    with pytest.raises(RuntimeError, match="shioaji said no"):
        api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-06-30")
    assert len(api.api.calls) == 3, "it kept going after the failure"


def test_a_failure_in_the_first_window_still_raises(api):
    api.api = FakeShioaji(fail_on=0)
    with pytest.raises(RuntimeError):
        api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-06-30")


# ══════════════════════════════════════════════════════════════════════════
#  Aggregation happens once, over the whole range
# ══════════════════════════════════════════════════════════════════════════

def test_one_minute_data_is_returned_without_aggregation(api, monkeypatch):
    """Shioaji only serves 1m, so that interval must skip the aggregator
    entirely rather than pass through an identity transform."""
    import cjtrade.pkgs.brokers.sinopac._internal_func as internal
    called = []

    def spy(kbars, target_interval):
        called.append(target_interval)
        return kbars

    monkeypatch.setattr(internal, "_aggregate_kbars", spy)
    bars = api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-04-02", "1m")
    assert len(bars) == 90
    assert called == [], "1m went through the aggregator"


def test_aggregation_sees_the_whole_range_not_one_window(api, monkeypatch):
    """A bar longer than a window -- 1w, 1M -- would be cut at the boundary
    and emitted twice as two partial bars if each window were aggregated on
    its own. So the aggregator must be called once, with everything."""
    seen = []

    def spy(kbars, target_interval):
        seen.append(len(kbars))
        return kbars

    import cjtrade.pkgs.brokers.sinopac._internal_func as internal
    monkeypatch.setattr(internal, "_aggregate_kbars", spy)

    api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-06-30", "1w")
    assert len(api.api.calls) > 1, "the range was not split, so this proves nothing"
    assert seen == [179], seen        # one call, every bar in the range


def test_an_unsupported_interval_is_reported_as_such(api, monkeypatch):
    import cjtrade.pkgs.brokers.sinopac._internal_func as internal

    def boom(kbars, target_interval):
        raise ValueError(f"unknown interval {target_interval}")

    monkeypatch.setattr(internal, "_aggregate_kbars", boom)
    with pytest.raises(ValueError, match="not supported"):
        api.get_kbars(Product(symbol=SYM), "2025-01-02", "2025-04-02", "7m")


# ══════════════════════════════════════════════════════════════════════════
#  The limit itself
# ══════════════════════════════════════════════════════════════════════════

def test_the_configured_limit_leaves_headroom_under_thirty_days():
    """The documented cap is 30 days and does not say whether the end date
    counts. 28 costs one extra request per 28 days of history, which is not a
    price worth paying the ambiguity for."""
    assert 0 < LIMIT <= 30
    assert LIMIT + 1 <= 30, "a window could land exactly on the documented cap"
