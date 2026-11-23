"""Build coarser bars from 1-minute bars, following the MarketData conventions."""
from __future__ import annotations

import math
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import List

from cjtrade.pkgs.marketdata.base import INTERVAL_MINUTES
from cjtrade.pkgs.models.kbar import Kbar

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
