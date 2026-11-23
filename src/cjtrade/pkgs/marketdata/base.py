"""The MarketData interface: where prices come from.

A MarketData knows nothing about accounts or orders. A broker that can only
place orders needs no MarketData of its own, and a backtest needs nothing but
a MarketData.

Conventions every implementation follows, so that sources can be swapped,
chained and cached without changing what a strategy sees:

* Windows are half-open, ``start <= bar.timestamp < end``. ``start`` and
  ``end`` may be a ``date``, a ``datetime`` or an ISO string; a date means
  00:00 of that day, so ``end="2025-09-02"`` stops before 2 September.
* Timestamps are naive Asia/Taipei time.
* Intraday bars are stamped at the minute they CLOSE: the first 1m bar of a
  session is 09:01, a 5m bar covering 09:00-09:05 is stamped 09:05.
* Daily bars are stamped 09:00 on the session date.
* Prices are raw, not adjusted for dividends or splits.
* Volume is in lots (張, 1,000 shares) for listed and OTC stocks.

Intervals are named ``1m 5m 15m 30m 1h 1d``. A source declares which ones it
serves through :attr:`MarketData.capabilities`, and asking for anything else
raises :class:`UnsupportedRequest` rather than returning an empty list, so a
:class:`~cjtrade.pkgs.marketdata.compose.Fallback` can move on to the next
source and a cache never records a window it was not given.
"""
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import FrozenSet
from typing import List
from typing import Union

from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.tick import Tick

TimeLike = Union[date, datetime, str]

INTRADAY_INTERVALS = ("1m", "5m", "15m", "30m", "1h")
INTERVALS = INTRADAY_INTERVALS + ("1d",)
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


class MarketDataError(Exception):
    """Base class for market data failures."""


class UnsupportedRequest(MarketDataError):
    """The source cannot serve this kind of request at all.

    Not a transient failure: asking again will not help. Raised for an
    interval the source does not offer, data behind a plan the account does
    not have, or a method the source does not implement.
    """


class MarketDataUnavailable(MarketDataError):
    """The source could not answer this time: network, rate limit, outage."""


@dataclass(frozen=True)
class Capabilities:
    """What a MarketData can serve.

    Attributes
    ----------
    intervals : frozenset of str
        Bar intervals ``get_kbars`` accepts.
    snapshots : bool
        Whether ``get_snapshots`` works.
    bid_ask : bool
        Whether ``get_bid_ask`` works.
    ticks : bool
        Whether ``get_ticks`` works.
    """

    intervals: FrozenSet[str] = field(default_factory=frozenset)
    snapshots: bool = False
    bid_ask: bool = False
    ticks: bool = False

    def __or__(self, other: "Capabilities") -> "Capabilities":
        return Capabilities(
            intervals=self.intervals | other.intervals,
            snapshots=self.snapshots or other.snapshots,
            bid_ask=self.bid_ask or other.bid_ask,
            ticks=self.ticks or other.ticks,
        )


class MarketData(ABC):
    """A source of prices. Subclass it to plug in a new one.

    Only :meth:`get_kbars` and :attr:`capabilities` are required. The other
    methods raise :class:`UnsupportedRequest` unless overridden, and
    ``capabilities`` must say which of them a subclass implements.

    Examples
    --------
    ```python
    class MyCSV(MarketData):
        name = "my-csv"

        @property
        def capabilities(self):
            return Capabilities(intervals=frozenset({"1d"}))

        def get_kbars(self, symbol, start, end, interval="1d"):
            self.require_interval(interval)
            start, end = to_window(start, end)
            return [k for k in read_my_csv(symbol) if start <= k.timestamp < end]
    ```
    """

    #: Short label, stored with every bar a cache keeps from this source.
    name: str = "custom"

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        """What this source can serve."""

    def supports(self, interval: str) -> bool:
        """Return whether ``get_kbars`` accepts `interval`."""
        return interval in self.capabilities.intervals

    def require_interval(self, interval: str) -> None:
        """Raise UnsupportedRequest unless `interval` is supported."""
        if not self.supports(interval):
            raise UnsupportedRequest(
                f"{self.name} does not serve {interval!r} bars "
                f"(it serves {sorted(self.capabilities.intervals) or 'none'})")

    @abstractmethod
    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        """Return the bars of `symbol` with ``start <= timestamp < end``.

        Parameters
        ----------
        symbol : str
            TWSE/TPEx code, e.g. ``"2330"``.
        start, end : date, datetime or str
            Half-open window; see the module docstring.
        interval : str
            One of ``capabilities.intervals``.

        Returns
        -------
        list of Kbar
            Oldest first. Empty when the window holds no bars.

        Raises
        ------
        UnsupportedRequest
            The interval, or the data behind it, is not available here.
        MarketDataUnavailable
            The source could not be reached.
        """

    def get_snapshots(self, symbols: List[str]) -> List[Snapshot]:
        """Return the latest quote of each symbol.

        Raises
        ------
        UnsupportedRequest
            Unless the subclass implements it.
        """
        raise UnsupportedRequest(f"{self.name} does not serve snapshots")

    def get_bid_ask(self, symbol: str, intraday_odd: bool = False) -> BidAsk:
        """Return the current order book of `symbol`.

        Raises
        ------
        UnsupportedRequest
            Unless the subclass implements it.
        """
        raise UnsupportedRequest(f"{self.name} does not serve bid/ask")

    def get_ticks(self, symbol: str, day: TimeLike) -> List[Tick]:
        """Return every trade print of `symbol` on `day`, oldest first.

        Raises
        ------
        UnsupportedRequest
            Unless the subclass implements it.
        """
        raise UnsupportedRequest(f"{self.name} does not serve ticks")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"


# ── helpers shared by implementations ─────────────────────────────────────────

def to_datetime(value: TimeLike) -> datetime:
    """Parse a date, datetime or ISO string into a naive datetime.

    A date (or a date-only string) becomes 00:00 of that day.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    return datetime.fromisoformat(text).replace(tzinfo=None)


def to_window(start: TimeLike, end: TimeLike) -> tuple[datetime, datetime]:
    """Parse a half-open window; returns ``(start, end)`` as datetimes."""
    return to_datetime(start), to_datetime(end)


def in_window(kbars: List[Kbar], start: datetime, end: datetime) -> List[Kbar]:
    """Keep the bars with ``start <= timestamp < end``, sorted, one per timestamp."""
    seen = set()
    out = []
    for k in sorted(kbars, key=lambda b: b.timestamp):
        if start <= k.timestamp < end and k.timestamp not in seen:
            seen.add(k.timestamp)
            out.append(k)
    return out


def session_days(start: datetime, end: datetime) -> List[date]:
    """Weekdays whose 09:00-13:30 session overlaps ``[start, end)``.

    Holidays are not excluded; a source returns nothing for them.
    """
    day = start.date()
    last = (end - timedelta(microseconds=1)).date()
    days = []
    while day <= last:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days
