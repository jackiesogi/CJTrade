from datetime import datetime

class Kbar:
    """One OHLCV bar (K線) for one symbol.

    `symbol` is optional only for backward compatibility; anything that merges
    bars from several symbols into one stream (multi-symbol backtest, live
    feed) needs it set.
    """

    def __init__(self, timestamp: datetime, open: float, high: float, low: float,
                 close: float, volume: int, symbol: str = ""):
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.symbol = symbol

    @classmethod
    def from_snapshot(cls, snapshot) -> "Kbar":
        """Treat a Snapshot as one closed bar. Used by live/replay runners.

        `close` and `timestamp` carry over exactly. `open`, `high`, `low` and
        `volume` do NOT describe this bar: a Snapshot reports the figures for
        the whole trading day so far -- that is what shioaji's api.snapshots()
        returns and what ArenaX now matches -- so on a 1m feed the high and low
        are the day's range, not the minute's, and they only widen as the
        session goes on.

        A strategy reading bar.close is fine. One reading bar.high/low wants
        real per-bar extremes and has to get them from get_kbars() instead.
        """
        return cls(
            timestamp=snapshot.timestamp,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
            symbol=snapshot.symbol,
        )

    def tagged(self, symbol: str) -> "Kbar":
        """Copy with `symbol` set. For sources that only know it one level up."""
        return Kbar(self.timestamp, self.open, self.high, self.low,
                    self.close, self.volume, symbol)

    def __repr__(self):
        return (f"Kbar(symbol={self.symbol}, timestamp={self.timestamp}, open={self.open}, "
                f"high={self.high}, low={self.low}, close={self.close}, volume={self.volume})")

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume
        }
