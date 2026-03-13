from datetime import datetime

class Kbar:
    def __init__(self, timestamp: datetime, open: float, high: float, low: float, close: float, volume: int):
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume

    def __repr__(self):
        return (f"Kbar(timestamp={self.timestamp}, open={self.open}, high={self.high}, "
                f"low={self.low}, close={self.close}, volume={self.volume})")
