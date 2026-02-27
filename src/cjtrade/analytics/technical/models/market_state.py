# Some classes that can represent the market state
from datetime import datetime


class OHLCVState:
    def __init__(self, ts: datetime, o: float, h: float, l: float, c: float, v: int):
        self.timestamp = ts
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v
