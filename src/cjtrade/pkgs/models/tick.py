"""One trade print (逐筆成交)."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TickSide(str, Enum):
    """Which side initiated the trade, when the source knows."""

    UNKNOWN = "UNKNOWN"
    BUY = "BUY"      # 外盤: a buyer took the ask
    SELL = "SELL"    # 內盤: a seller hit the bid


@dataclass(frozen=True)
class Tick:
    """One trade print.

    Attributes
    ----------
    timestamp : datetime
        Naive Asia/Taipei time of the trade.
    price : float
        Trade price.
    volume : int
        Trade size in lots (張, 1,000 shares) for listed stocks.
    symbol : str
        Ticker.
    side : TickSide
        Initiating side; UNKNOWN when the source cannot tell.
    """

    timestamp: datetime
    price: float
    volume: int
    symbol: str
    side: TickSide = TickSide.UNKNOWN
