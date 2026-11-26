"""Build bars from finer data: 1m bars from ticks, coarser bars from 1m.

Both follow the MarketData conventions, so a source that only has the finer
data can still serve every interval.
"""
from __future__ import annotations

import math
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import List

from cjtrade.pkgs.marketdata.base import INTERVAL_MINUTES
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.tick import Tick

SESSION_OPEN = time(9, 0)
SESSION_CLOSE = time(13, 30)


def _bucket_end(ts: datetime, minutes: int) -> datetime:
    """End stamp of the `minutes`-wide bucket holding the 1m bar closing at `ts`."""
    open_ = ts.replace(hour=SESSION_OPEN.hour, minute=SESSION_OPEN.minute,
                       second=0, microsecond=0)
    elapsed = (ts - open_).total_seconds() / 60.0
    end = open_ + timedelta(minutes=max(1, math.ceil(elapsed / minutes)) * minutes)
    close = ts.replace(hour=SESSION_CLOSE.hour, minute=SESSION_CLOSE.minute,
                       second=0, microsecond=0)
    return min(end, close) if ts <= close else end


def _merge(group: List[Kbar], stamp: datetime, symbol: str) -> Kbar:
    return Kbar(
        timestamp=stamp,
        open=group[0].open,
        high=max(k.high for k in group),
        low=min(k.low for k in group),
        close=group[-1].close,
        volume=sum(int(k.volume) for k in group),
        symbol=symbol,
    )


def aggregate(minute_bars: List[Kbar], interval: str) -> List[Kbar]:
    """Aggregate 1m bars into `interval` bars.

    Parameters
    ----------
    minute_bars : list of Kbar
        1-minute bars stamped at the minute they close.
    interval : str
        ``1m``, ``5m``, ``15m``, ``30m``, ``1h`` or ``1d``.

    Returns
    -------
    list of Kbar
        Intraday bars stamped at their bucket's close (the last bucket of a
        session ends at 13:30); daily bars stamped 09:00 on the session date.

    Raises
    ------
    ValueError
        For any other interval.
    """
    bars = sorted(minute_bars, key=lambda k: k.timestamp)
    if interval == "1m" or not bars:
        return bars
    if interval == "1d":
        key = lambda k: k.timestamp.date()                       # noqa: E731
        stamp = lambda d: datetime(d.year, d.month, d.day, 9, 0)  # noqa: E731
    elif interval in INTERVAL_MINUTES:
        width = INTERVAL_MINUTES[interval]
        key = lambda k: _bucket_end(k.timestamp, width)           # noqa: E731
        stamp = lambda end: end                                   # noqa: E731
    else:
        raise ValueError(f"cannot aggregate to {interval!r}")

    out: List[Kbar] = []
    group: List[Kbar] = []
    current = None
    for k in bars:
        bucket = key(k)
        if group and bucket != current:
            out.append(_merge(group, stamp(current), group[0].symbol))
            group = []
        current = bucket
        group.append(k)
    if group:
        out.append(_merge(group, stamp(current), group[0].symbol))
    return out


def bars_from_ticks(ticks: List[Tick]) -> List[Kbar]:
    """Build 1m bars from trade prints.

    A print at ``hh:mm:ss`` belongs to the bar closing at ``hh:mm+1``, so a
    09:00:30 print lands in the 09:01 bar. The closing auction prints at
    13:30 and is folded into the 13:30 bar rather than opening a 13:31 one.
    Minutes without a print get no bar.

    Parameters
    ----------
    ticks : list of Tick
        Any order; volumes in lots.

    Returns
    -------
    list of Kbar
        Oldest first, stamped at their close. The last bar may still be
        forming; pass the result through
        :func:`~cjtrade.pkgs.marketdata.base.closed` to drop it.
    """
    out: List[Kbar] = []
    group: List[Tick] = []
    current = None
    for t in sorted(ticks, key=lambda t: t.timestamp):
        stamp = t.timestamp.replace(second=0, microsecond=0) + timedelta(minutes=1)
        close = t.timestamp.replace(hour=SESSION_CLOSE.hour, minute=SESSION_CLOSE.minute,
                                    second=0, microsecond=0)
        if stamp == close + timedelta(minutes=1):     # 13:30:xx auction print
            stamp = close
        if group and stamp != current:
            out.append(_from_ticks(group, current))
            group = []
        current = stamp
        group.append(t)
    if group:
        out.append(_from_ticks(group, current))
    return out


def _from_ticks(group: List[Tick], stamp: datetime) -> Kbar:
    prices = [t.price for t in group]
    return Kbar(timestamp=stamp, open=prices[0], high=max(prices), low=min(prices),
                close=prices[-1], volume=sum(int(t.volume) for t in group),
                symbol=group[0].symbol)
