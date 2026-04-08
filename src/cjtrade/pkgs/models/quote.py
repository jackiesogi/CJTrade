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
    symbol: str
    datetime: datetime
    bid_price: List[float]  # Five levels
    bid_volume: List[int]
    ask_price: List[float]
    ask_volume: List[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "datetime": self.datetime.isoformat(),
            "bid_price": self.bid_price,
            "bid_volume": self.bid_volume,
            "ask_price": self.ask_price,
            "ask_volume": self.ask_volume,
        }
