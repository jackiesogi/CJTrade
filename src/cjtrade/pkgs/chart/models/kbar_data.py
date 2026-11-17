from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from cjtrade.pkgs.analytics.technical.models.market_state import OHLCVState


@dataclass
class KbarData:
    """One K-bar (OHLCV candle) for charting.

    Parameters
    ----------
    timestamp : datetime
        Bar time.
    open, high, low, close : float
        Bar prices.
    volume : int
        Traded volume.
    symbol : str, optional
        Product symbol.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    symbol: Optional[str] = None

    @classmethod
    def from_ohlcv_state(cls, state: OHLCVState, symbol: Optional[str] = None) -> 'KbarData':
        """Build a `KbarData` from an `OHLCVState`.

        Parameters
        ----------
        state : OHLCVState
            Source bar.
        symbol : str, optional
            Product symbol to attach.

        Returns
        -------
        KbarData
            The converted bar.
        """
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
        """Convert this bar to an `OHLCVState` (the symbol is dropped)."""
        return OHLCVState(
            ts=self.timestamp,
            o=self.open,
            h=self.high,
            l=self.low,
            c=self.close,
            v=self.volume
        )
