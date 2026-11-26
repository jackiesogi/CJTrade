"""ArenaXMarketData: read prices from a running ArenaX server."""
from __future__ import annotations

from typing import List

from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot

_SERVER_INTERVALS = frozenset({"1m", "5m", "1h", "1d"})


class ArenaXMarketData(MarketData):
    """The prices an ArenaX server is simulating with.

    Use this, not a separate source, when trading against ArenaX: the
    server fills orders against its own data, so a strategy must see the
    same bars. Which source the server reads from is chosen when the server
    starts (``arenaxd --data=...``). "Now", for which bars have closed, is the
    server's simulated clock, not the wall clock.

    Parameters
    ----------
    broker : ArenaXBrokerAPI_v2 or AccountClient
        An ArenaX broker client.

    Warnings
    --------
    Makes HTTP calls to the server. Its bid/ask book is simulated around the
    last close, not real.
    """

    name = "arenax"

    def __init__(self, broker) -> None:
        self.broker = getattr(broker, "broker_api", broker)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(intervals=_SERVER_INTERVALS, snapshots=True, bid_ask=True)

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        if end_dt <= start_dt:
            return []
        # Datetimes, which the route takes as a half-open window. The server
        # leaves out bars that have not closed on its simulated clock.
        bars = self.broker.get_kbars(Product(symbol=symbol),
                                     start_dt.isoformat(timespec="seconds"),
                                     end_dt.isoformat(timespec="seconds"), interval)
        return in_window(bars or [], start_dt, end_dt)

    def get_snapshots(self, symbols: List[str]) -> List[Snapshot]:
        return self.broker.get_snapshots([Product(symbol=s) for s in symbols])

    def get_bid_ask(self, symbol: str, intraday_odd: bool = False) -> BidAsk:
        return self.broker.get_bid_ask(Product(symbol=symbol), intraday_odd)
