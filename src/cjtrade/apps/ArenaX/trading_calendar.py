"""Taiwan equity trading sessions.

The only place that knows 09:00 and 13:30. Those literals used to be copied
across nine sites (market_data, brokerside_server, sinopac_broker_api,
cjtrade_system_arenax), so "when does the market close" had nine answers that
had to be kept in step by hand.

Pure: no clock, no I/O, no state. Pass the time in.

Usage::

    from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
    from cjtrade.pkgs.models.order import OrderLot

    cal = TradingCalendar()
    cal.is_open(OrderLot.Common, t)              # 盤中 09:00-13:30
    cal.close_of(OrderLot.Common, t)             # that day's 13:30
    cal.next_open(OrderLot.Common, t)            # next session open

Sessions (ROC market rules):
  regular           09:00-13:30  一般交易
  intraday_odd      09:10-13:30  盤中零股
  after_hours_odd   13:40-14:30  盤後零股

NOTE: is_open(OrderLot.IntraDayOdd) answers the real 盤中零股 window, but
ArenaX does not yet route orders by lot — place_order asks about the regular
session for everything. Making odd-lot orders obey their own window is a
behaviour change and belongs in its own commit.
"""
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Optional

from cjtrade.pkgs.models.order import OrderLot


@dataclass(frozen=True)
class Session:
    name: str
    open: time
    close: time

    def contains(self, t: time) -> bool:
        return self.open <= t <= self.close


class TradingCalendar:
    """Which sessions exist, and when.

    Weekends only — no holiday calendar yet, so a national holiday still reads
    as a trading day. See pkgs/utils/ncal.py for the holiday data that would
    feed `is_trading_day`.
    """

    REGULAR = Session("regular", time(9, 0), time(13, 30))
    INTRADAY_ODD = Session("intraday_odd", time(9, 10), time(13, 30))
    AFTER_HOURS_ODD = Session("after_hours_odd", time(13, 40), time(14, 30))

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5

    def sessions_for(self, lot: OrderLot) -> tuple:
        """Sessions an order of this lot type may trade in, earliest first."""
        if lot == OrderLot.IntraDayOdd:
            return (self.INTRADAY_ODD, self.AFTER_HOURS_ODD)
        return (self.REGULAR,)

    def session_at(self, lot: OrderLot, t: datetime) -> Optional[Session]:
        """The session `t` falls inside, or None when nothing is trading."""
        if not self.is_trading_day(t.date()):
            return None
        for s in self.sessions_for(lot):
            if s.contains(t.time()):
                return s
        return None

    def is_open(self, lot: OrderLot, t: datetime) -> bool:
        return self.session_at(lot, t) is not None

    def close_of(self, lot: OrderLot, t: datetime) -> datetime:
        """End of the last session of `t`'s day — when a ROD order expires."""
        last = self.sessions_for(lot)[-1]
        return datetime.combine(t.date(), last.close)

    def next_open(self, lot: OrderLot, t: datetime) -> datetime:
        """The next moment trading starts at or after `t`.

        Looks at today first. The server's old `_skip_to_trading_hours` always
        jumped to tomorrow 09:00, so a run starting at 08:00 on a weekday threw
        away that whole day's session.
        """
        day = t.date()
        for _ in range(8):           # today plus a week covers any weekend
            if self.is_trading_day(day):
                for s in self.sessions_for(lot):
                    start = datetime.combine(day, s.open)
                    if start >= t:
                        return start
            day += timedelta(days=1)
            t = datetime.combine(day, time(0, 0))
        raise RuntimeError(f"no trading session found within a week of {t}")
