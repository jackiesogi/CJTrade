"""A snapshot's open/high/low must describe one trading day, not the whole run.

`Snapshot` means "today so far plus the latest price" -- that is what shioaji's
api.snapshots() returns, and what paper/real therefore hand the engine. The
simulated backend used to aggregate from row 0 of its entire preloaded range,
so `open` was the first bar of the backtest and `high`/`low` were the running
extremes over every loaded day. Verified before the fix: at 10:00 the bar was
O253.5 H254.0 L253.5 C254.0 while the snapshot reported O253.0 H256.0 L251.0.
"""
from datetime import datetime
from datetime import timedelta

import pandas as pd
import pytest
from cjtrade.apps.ArenaX.base_backend import ArenaX_AccountState
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs.models.cost import CostModel
from cjtrade.pkgs.models.order import OrderLot

D1 = datetime(2025, 9, 1)       # Monday
D2 = datetime(2025, 9, 2)


class _StubMarket:
    def __init__(self, rows):
        index = pd.DatetimeIndex([r[0] for r in rows])
        self.historical_data = {
            "2317": {
                "data": pd.DataFrame(
                    {
                        "Open":   [r[1] for r in rows],
                        "High":   [r[2] for r in rows],
                        "Low":    [r[3] for r in rows],
                        "Close":  [r[4] for r in rows],
                        "Volume": [r[5] for r in rows],
                    },
                    index=index,
                ),
                "timestamps": index.to_numpy(),
            }
        }
        self.start_date = index[0].to_pydatetime()
        self.calendar = TradingCalendar()
        self.now = self.start_date

    def get_market_time(self):
        return {"mock_current_time": self.now, "mock_init_time": self.start_date}

    def is_market_open(self):
        return self.calendar.is_open(OrderLot.Common, self.now)

    def adjust_to_market_hours(self, t):
        return t


def _bars(day, specs, first_minute=1):
    """specs: list of (open, high, low, close). One bar per minute from 09:01."""
    base = day.replace(hour=9, minute=first_minute)
    return [(base + timedelta(minutes=i), o, h, lo, c, 100)
            for i, (o, h, lo, c) in enumerate(specs)]


def _backend(rows) -> ArenaX_BackendBase:
    b = ArenaX_BackendBase.__new__(ArenaX_BackendBase)
    b.account_state = ArenaX_AccountState()
    b._cost_model = CostModel()
    b.real_account = None
    b.num_days_preload = 5
    b.market = _StubMarket(rows)
    return b


# Day 1 deliberately brackets day 2 on BOTH sides -- a higher high (110) and a
# lower low (85) -- so every one of open/high/low discriminates the old
# whole-range aggregate from the new per-day one. Day 2 trades 88-92.
DAY1 = _bars(D1, [(100.0, 110.0, 99.0, 105.0),
                  (105.0, 106.0, 85.0, 106.0),
                  (106.0, 107.0, 100.0, 101.0)])
DAY2 = _bars(D2, [(90.0, 91.0, 89.0, 90.5),
                  (90.5, 92.0, 90.0, 91.0),
                  (91.0, 91.5, 88.0, 88.5)])


class TestDailyAggregation:
    def test_open_is_todays_open_not_the_runs_first_bar(self):
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=2)
        snap = b.snapshot("2317")
        assert snap.open == pytest.approx(90.0)      # day 2's first bar
        # Day 1's first open was 100.0 — the old slice reported that forever.
        assert snap.open != pytest.approx(100.0)

    def test_high_and_low_are_todays_only(self):
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=2)
        snap = b.snapshot("2317")
        assert snap.high == pytest.approx(92.0)      # max over day 2 so far
        assert snap.low == pytest.approx(89.0)       # min over day 2 so far
        # Day 1 reached 110.0 and 85.0; the old slice reported exactly those.
        assert snap.high != pytest.approx(110.0)
        assert snap.low != pytest.approx(85.0)

    def test_high_low_accumulate_within_the_day(self):
        """Each is the extreme over the day *so far*, so they widen bar by bar."""
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=1)
        early = b.snapshot("2317")
        b.market.now = D2.replace(hour=9, minute=3)
        late = b.snapshot("2317")
        assert (early.high, early.low) == pytest.approx((91.0, 89.0))  # bar 1 only
        assert (late.high, late.low) == pytest.approx((92.0, 88.0))    # bars 1-3

    def test_close_is_the_bar_at_the_clock(self):
        b = _backend(DAY1 + DAY2)
        for minute, expected in ((1, 90.5), (2, 91.0), (3, 88.5)):
            b.market.now = D2.replace(hour=9, minute=minute)
            assert b.snapshot("2317").close == pytest.approx(expected)

    def test_first_bar_of_a_day_reports_that_bar_alone(self):
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=1)
        snap = b.snapshot("2317")
        assert (snap.open, snap.high, snap.low, snap.close) == pytest.approx(
            (90.0, 91.0, 89.0, 90.5))

    def test_single_day_of_data_is_unaffected(self):
        """With one day loaded, per-day and whole-range agree — the guard that
        the fix changes nothing for a single-session run."""
        b = _backend(DAY1)
        b.market.now = D1.replace(hour=9, minute=3)
        snap = b.snapshot("2317")
        assert (snap.open, snap.high, snap.low, snap.close) == pytest.approx(
            (100.0, 110.0, 85.0, 101.0))


class TestBeforeTheFirstBarOfASession:
    def test_reports_the_previous_session_rather_than_a_random_fallback(self):
        """The data starts at 09:01, so 09:00 has no bar of its own.

        Keying the day slice on the requested timestamp would select nothing
        and drop through to _create_fallback_snapshot, which invents a price
        around 100 with random(). Keying on the latest bar's day gives the
        previous session's figures instead.
        """
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=0)
        snap = b.snapshot("2317")
        # Day 1's own figures. Exact values also prove this is not the random
        # fallback, which invents a price around 100 with random().
        assert (snap.open, snap.high, snap.low, snap.close) == pytest.approx(
            (100.0, 110.0, 85.0, 101.0))


class TestDerivedFields:
    def test_action_compares_close_against_the_days_open(self):
        """Up or down on the day. Does not discriminate the fix on this data --
        both the old and new `open` sit above day 2's close -- but it pins the
        meaning so a future change to `open` cannot silently invert it."""
        from cjtrade.pkgs.models.order import OrderAction
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=3)
        assert b.snapshot("2317").action == OrderAction.SELL

    def test_average_price_is_the_days_midpoint(self):
        b = _backend(DAY1 + DAY2)
        b.market.now = D2.replace(hour=9, minute=2)
        snap = b.snapshot("2317")
        assert snap.average_price == pytest.approx(round((92.0 + 89.0) / 2, 2))
