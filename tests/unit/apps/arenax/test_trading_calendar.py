"""Unit tests for TradingCalendar — pure session arithmetic."""
from datetime import date
from datetime import datetime

import pytest
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs.models.order import OrderLot

CAL = TradingCalendar()
COMMON = OrderLot.Common
ODD = OrderLot.IntraDayOdd

# 2025-09-01 is a Monday, 2025-09-06/07 are Sat/Sun.
MON = date(2025, 9, 1)
FRI = date(2025, 9, 5)
SAT = date(2025, 9, 6)


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


# ── Trading days ──────────────────────────────────────────────────────────────

class TestTradingDay:
    def test_weekday_is_trading_day(self):
        assert CAL.is_trading_day(MON) is True
        assert CAL.is_trading_day(FRI) is True

    def test_weekend_is_not(self):
        assert CAL.is_trading_day(SAT) is False
        assert CAL.is_trading_day(date(2025, 9, 7)) is False


# ── Regular session ───────────────────────────────────────────────────────────

class TestRegularSession:
    @pytest.mark.parametrize("h,m,expected", [
        (8, 59, False),
        (9, 0, True),      # inclusive open
        (11, 0, True),
        (13, 30, True),    # inclusive close
        (13, 31, False),
        (14, 0, False),
    ])
    def test_boundaries(self, h, m, expected):
        assert CAL.is_open(COMMON, at(MON, h, m)) is expected

    def test_closed_all_weekend(self):
        assert CAL.is_open(COMMON, at(SAT, 11)) is False

    def test_close_of_day(self):
        assert CAL.close_of(COMMON, at(MON, 9, 30)) == at(MON, 13, 30)


# ── Odd-lot sessions ──────────────────────────────────────────────────────────

class TestOddLotSessions:
    def test_intraday_odd_starts_at_0910(self):
        assert CAL.is_open(ODD, at(MON, 9, 5)) is False
        assert CAL.is_open(ODD, at(MON, 9, 10)) is True

    def test_after_hours_odd_window(self):
        assert CAL.is_open(ODD, at(MON, 13, 35)) is False
        assert CAL.is_open(ODD, at(MON, 13, 40)) is True
        assert CAL.is_open(ODD, at(MON, 14, 30)) is True
        assert CAL.is_open(ODD, at(MON, 14, 31)) is False

    def test_regular_lot_is_closed_in_the_odd_window(self):
        assert CAL.is_open(COMMON, at(MON, 14, 0)) is False

    def test_odd_lot_expires_at_the_later_close(self):
        assert CAL.close_of(ODD, at(MON, 9, 30)) == at(MON, 14, 30)

    def test_session_at_names_the_session(self):
        assert CAL.session_at(ODD, at(MON, 10, 0)).name == "intraday_odd"
        assert CAL.session_at(ODD, at(MON, 14, 0)).name == "after_hours_odd"
        assert CAL.session_at(ODD, at(MON, 9, 0)) is None


# ── next_open ─────────────────────────────────────────────────────────────────

class TestNextOpen:
    def test_before_the_open_returns_today(self):
        """The server's old jump always went to tomorrow and lost a session."""
        assert CAL.next_open(COMMON, at(MON, 8, 0)) == at(MON, 9, 0)

    def test_at_the_open_returns_now(self):
        assert CAL.next_open(COMMON, at(MON, 9, 0)) == at(MON, 9, 0)

    def test_after_the_close_returns_tomorrow(self):
        assert CAL.next_open(COMMON, at(MON, 14, 0)) == at(date(2025, 9, 2), 9, 0)

    def test_friday_evening_skips_the_weekend(self):
        assert CAL.next_open(COMMON, at(FRI, 14, 0)) == at(date(2025, 9, 8), 9, 0)

    def test_saturday_skips_to_monday(self):
        assert CAL.next_open(COMMON, at(SAT, 11, 0)) == at(date(2025, 9, 8), 9, 0)

    def test_odd_lot_second_session_same_day(self):
        assert CAL.next_open(ODD, at(MON, 13, 35)) == at(MON, 13, 40)


if __name__ == "__main__":
    pytest.main([__file__])
