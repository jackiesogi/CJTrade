from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs.models.order import *


@dataclass
class Quote:
    """Last price and volume of a symbol.

    Attributes
    ----------
    symbol : str
        Ticker.
    price : float
        Last price.
    volume : int
        Volume.
    timestamp : str
        Time of the quote.
    """
    symbol: str
    price: float
    volume: int
    timestamp: str

# ts=1673620200000000000,
# code='2330',
# exchange='TSE',
# open=507.0,
# high=509.0,
# low=499.0,
# close=500.0,
# tick_type=<TickType.Sell: 'Sell'>,
# change_price=13.5,
# change_rate=2.77,
# change_type=<ChangeType.Up: 'Up'>,
# average_price=502.42,
# volume=48,
# total_volume=77606,
# amount=24000000,
# total_amount=38990557755,
# yesterday_volume=20963.0,
# buy_price=500.0,
# buy_volume=122.0,
# sell_price=501.0,
# sell_volume=1067,
# volume_ratio=3.7
# OCHLV
@dataclass
class Snapshot:
    """Market snapshot of one symbol: day OHLCV plus best bid and ask.

    ``open``, ``high``, ``low`` and ``volume`` cover the trading day so far,
    not a single bar (see `Kbar.from_snapshot`).

    Attributes
    ----------
    symbol : str
        Ticker.
    exchange : str
        Exchange code, e.g. ``"TSE"``.
    timestamp : datetime
        Time of the snapshot.
    open, close, high, low : float
        Day prices; ``close`` is the latest price.
    volume : int
        Volume.
    average_price : float
        Average traded price.
    action : OrderAction
        Side of the last trade (buy, sell or none).
    buy_price, sell_price : float
        Best bid and best ask.
    buy_volume, sell_volume : int
        Volume at the best bid and best ask.
    additional_note : str, optional
        Free-form note.
    """
    symbol: str
    exchange: str
    timestamp: datetime
    open: float
    close: float
    high: float
    low: float
    volume: int
    average_price: float
    action: OrderAction  # Buy/Sell/None
    buy_price: float
    buy_volume: int
    sell_price: float
    sell_volume: int
    additional_note: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Snapshot":
        """Build a Snapshot from a dict such as the one `to_dict` returns.

        Parameters
        ----------
        d : dict
            Snapshot fields. ``timestamp`` may be an ISO string and ``action``
            a string; both are converted.

        Returns
        -------
        Snapshot

        Raises
        ------
        KeyError
            If a required field is missing.
        """
        ts = d.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        action = d.get("action")
        if isinstance(action, str):
            action = OrderAction(action)
        return cls(
            symbol=d["symbol"],
            exchange=d["exchange"],
            timestamp=ts,
            open=float(d["open"]),
            close=float(d["close"]),
            high=float(d["high"]),
            low=float(d["low"]),
            volume=int(d["volume"]),
            average_price=float(d["average_price"]),
            action=action,
            buy_price=float(d["buy_price"]),
            buy_volume=int(d["buy_volume"]),
            sell_price=float(d["sell_price"]),
            sell_volume=int(d["sell_volume"]),
            additional_note=d.get("additional_note"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return the snapshot as a JSON-friendly dict (ISO timestamp, enum values as strings)."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "close": self.close,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "average_price": self.average_price,
            "action": self.action.value if hasattr(self.action, 'value') else self.action,
            "buy_price": self.buy_price,
            "buy_volume": self.buy_volume,
            "sell_price": self.sell_price,
            "sell_volume": self.sell_volume,
            "additional_note": self.additional_note,
        }


@dataclass
class BidAsk:
    """Five-level order book of one symbol.

    Attributes
    ----------
    symbol : str
        Ticker.
    datetime : datetime
        Time of the book.
    bid_price, ask_price : list of float
        Prices of the five bid and ask levels.
    bid_volume, ask_volume : list of int
        Volumes of the five bid and ask levels.
    """
    symbol: str
    datetime: datetime
    bid_price: List[float]  # Five levels
    bid_volume: List[int]
    ask_price: List[float]
    ask_volume: List[int]

    def to_dict(self) -> Dict[str, Any]:
        """Return the order book as a JSON-friendly dict."""
        return {
            "symbol": self.symbol,
            "datetime": self.datetime.isoformat(),
            "bid_price": self.bid_price,
            "bid_volume": self.bid_volume,
            "ask_price": self.ask_price,
            "ask_volume": self.ask_volume,
        }
