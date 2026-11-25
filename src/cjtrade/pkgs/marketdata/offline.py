"""OfflineMarketData: a source that never has anything.

Put it behind a cache to serve only what is already on disk:
``Cached(OfflineMarketData(), PriceCache(path))``, or ``arenaxd --data=offline``.
"""
from __future__ import annotations

from typing import List

from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import INTERVALS
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.models.kbar import Kbar


class OfflineMarketData(MarketData):
    """Answers every bar request with no bars and makes no network call.

    It claims every interval so that a :class:`~cjtrade.pkgs.marketdata.compose.Cached`
    in front of it serves whatever the cache holds for any interval, and a
    window the cache lacks simply comes back empty. Snapshots, bid/ask and
    ticks are unsupported.
    """

    name = "offline"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(intervals=frozenset(INTERVALS))

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        return []
