# Some classes that can represent the market state

class OHLCVState:
    def __init__(self, o: float, h: float, l: float, c: float, v: int):
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v