from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from cjtrade.analytics.technical.models.market_state import OHLCVState


@dataclass
class KbarData:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    symbol: Optional[str] = None

    @classmethod
    def from_ohlcv_state(cls, state: OHLCVState, symbol: Optional[str] = None) -> 'KbarData':
        return cls(
            timestamp=state.timestamp,
            open=state.open,
            high=state.high,
            low=state.low,
            close=state.close,
            volume=state.volume,
            symbol=symbol
        )

    def to_ohlcv_state(self) -> OHLCVState:
        return OHLCVState(
            ts=self.timestamp,
            o=self.open,
            h=self.high,
            l=self.low,
            c=self.close,
            v=self.volume
        )