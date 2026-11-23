"""SinopacMarketData: bars and quotes through a Sinopac (shioaji) session."""
from __future__ import annotations

from datetime import timedelta
from typing import List

from cjtrade.pkgs.marketdata.aggregate import aggregate
from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import INTERVALS
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import MarketDataUnavailable
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot


class SinopacMarketData(MarketData):
    """Market data from a connected Sinopac session.

    Shares the session of the broker it is given, so it adds no login of its
    own. Bars are fetched as 1m and aggregated here, so every interval
    follows the MarketData stamping rules.

    Parameters
    ----------
    broker : SinopacBrokerAPI or AccountClient
        A Sinopac broker. It must be connected before data is requested.

    Warnings
    --------
    Makes network calls through the shioaji session. Quotes are whatever
    the account's market-data permissions allow.
    """

    name = "sinopac"

    def __init__(self, broker) -> None:
        self.broker = getattr(broker, "broker_api", broker)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(intervals=frozenset(INTERVALS), snapshots=True, bid_ask=True)

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        if end_dt <= start_dt:
            return []
        # Sinopac takes whole dates, end exclusive.
        last = end_dt - timedelta(microseconds=1)
        try:
            minutes = self.broker.get_kbars(
                Product(symbol=symbol), start_dt.strftime("%Y-%m-%d"),
                (last + timedelta(days=1)).strftime("%Y-%m-%d"), "1m")
        except ConnectionError as e:
            raise MarketDataUnavailable(f"sinopac: {e}") from e
        return in_window(aggregate(minutes or [], interval), start_dt, end_dt)

    def get_snapshots(self, symbols: List[str]) -> List[Snapshot]:
        try:
            return self.broker.get_snapshots([Product(symbol=s) for s in symbols])
        except ConnectionError as e:
            raise MarketDataUnavailable(f"sinopac: {e}") from e

    def get_bid_ask(self, symbol: str, intraday_odd: bool = False) -> BidAsk:
        try:
            return self.broker.get_bid_ask(Product(symbol=symbol), intraday_odd)
        except ConnectionError as e:
            raise MarketDataUnavailable(f"sinopac: {e}") from e
