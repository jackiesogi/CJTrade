"""Combine MarketData sources: try several in turn, or put a cache in front."""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from functools import reduce
from typing import List
from typing import Sequence

from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import one_line
from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import is_offline
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_datetime
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.marketdata.base import UnsupportedRequest
from cjtrade.pkgs.marketdata.cache import PriceCache
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.tick import Tick

log = get_logger("marketdata")


class Fallback(MarketData):
    """Ask each source in order; the first non-empty answer wins.

    A source that does not support the request is skipped. One that fails or
    returns nothing is logged and the next one is asked. Its capabilities are
    the union of its sources'.

    Parameters
    ----------
    sources : sequence of MarketData
        In order of preference.

    Attributes
    ----------
    last_source : str or None
        Name of the source that answered the latest ``get_kbars`` call.

    Examples
    --------
    ```python
    market = Fallback([FinMindMarketData(token="..."), YFinanceMarketData()])
    market.get_kbars("2330", "2025-01-01", "2025-07-01", "1d")   # FinMind
    market.get_kbars("2330", "2025-06-02", "2025-06-03", "1m")   # yfinance
    ```
    """

    def __init__(self, sources: Sequence[MarketData]) -> None:
        if not sources:
            raise ValueError("Fallback needs at least one source")
        self.sources = list(sources)
        self.name = "+".join(s.name for s in self.sources)
        self.last_source = None

    @property
    def capabilities(self) -> Capabilities:
        return reduce(lambda a, b: a | b, (s.capabilities for s in self.sources))

    def _try(self, method: str, wanted, *args):
        tried = False
        for source in self.sources:
            if not wanted(source):
                continue
            tried = True
            try:
                result = getattr(source, method)(*args)
            except UnsupportedRequest:
                continue
            except Exception as e:                       # noqa: BLE001
                report = log.debug if is_offline() else log.warning
                report("%s.%s failed, trying the next source: %s",
                       source.name, method, e)
                continue
            if result:
                return source, result
        if not tried:
            raise UnsupportedRequest(f"no source in {self.name} serves {method}{args[-1:]}")
        return None, None

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        source, bars = self._try("get_kbars", lambda s: s.supports(interval),
                                 symbol, start, end, interval)
        self.last_source = source.name if source else None
        return bars or []

    def get_snapshots(self, symbols: List[str]) -> List[Snapshot]:
        _, snaps = self._try("get_snapshots", lambda s: s.capabilities.snapshots, symbols)
        return snaps or []

    def get_bid_ask(self, symbol: str, intraday_odd: bool = False) -> BidAsk:
        _, book = self._try("get_bid_ask", lambda s: s.capabilities.bid_ask,
                            symbol, intraday_odd)
        return book

    def get_ticks(self, symbol: str, day: TimeLike) -> List[Tick]:
        _, ticks = self._try("get_ticks", lambda s: s.capabilities.ticks, symbol, day)
        return ticks or []


class Cached(MarketData):
    """Serve bars from a local cache, fetching only the windows it lacks.

    Each missing window is fetched in chunks (30 days for intraday bars, a
    year for daily ones). A chunk that comes back with bars is stored and
    recorded as fetched; one that comes back empty is not, so it is asked for
    again next time rather than treated as permanently empty. A recorded
    window never reaches past the present.

    Snapshots, bid/ask and ticks are live data and pass straight through.

    Parameters
    ----------
    source : MarketData
        Where missing bars come from.
    cache : PriceCache, optional
        Defaults to ``PriceCache()``, the shared cache file.

    Warnings
    --------
    Writes every fetched bar to the cache file.
    """

    INTRADAY_CHUNK = timedelta(days=30)
    DAILY_CHUNK = timedelta(days=366)

    def __init__(self, source: MarketData, cache: PriceCache | None = None) -> None:
        self.source = source
        self.cache = cache if cache is not None else PriceCache()
        self.name = f"cached({source.name})"

    @property
    def capabilities(self) -> Capabilities:
        return self.source.capabilities

    def _chunks(self, start: datetime, end: datetime, interval: str):
        step = self.DAILY_CHUNK if interval == "1d" else self.INTRADAY_CHUNK
        while start < end:
            stop = min(start + step, end)
            yield start, stop
            start = stop

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        for gap_start, gap_end in self.cache.missing(symbol, interval, start_dt, end_dt):
            for chunk_start, chunk_end in self._chunks(gap_start, gap_end, interval):
                try:
                    bars = self.source.get_kbars(symbol, chunk_start, chunk_end, interval)
                except UnsupportedRequest:
                    raise
                except Exception as e:                   # noqa: BLE001
                    # A failed chunk stays a gap, to be asked for again.
                    # Offline that is expected, so it is not worth a warning.
                    report = log.debug if is_offline() else log.warning
                    report("%s: %s %s [%s, %s) not fetched: %s", self.source.name,
                           one_line(symbol), one_line(interval), chunk_start,
                           chunk_end, e)
                    continue
                if not bars:
                    continue
                label = getattr(self.source, "last_source", None) or self.source.name
                self.cache.store(symbol, interval, bars, label)
                self.cache.mark_fetched(symbol, interval, chunk_start, chunk_end, label)
        return in_window(self.cache.get_kbars(symbol, start_dt, end_dt, interval),
                         start_dt, end_dt)

    def get_snapshots(self, symbols: List[str]) -> List[Snapshot]:
        return self.source.get_snapshots(symbols)

    def get_bid_ask(self, symbol: str, intraday_odd: bool = False) -> BidAsk:
        return self.source.get_bid_ask(symbol, intraday_odd)

    def get_ticks(self, symbol: str, day: TimeLike) -> List[Tick]:
        return self.source.get_ticks(symbol, to_datetime(day))
