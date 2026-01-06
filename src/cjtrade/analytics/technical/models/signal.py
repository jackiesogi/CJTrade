from enum import Enum

class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class Signal:
    def __init__(self, action: SignalAction = SignalAction.HOLD, reason: str = ""):
        self.action = action
        self.reason = reason