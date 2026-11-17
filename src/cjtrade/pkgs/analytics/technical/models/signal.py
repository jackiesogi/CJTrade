from enum import Enum

class SignalAction(str, Enum):
    """Trading action of a `Signal`."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class Signal:
    """A trading signal with a human-readable reason.

    Parameters
    ----------
    action : SignalAction
        Defaults to HOLD.
    reason : str
        Why the signal was produced.
    """
    def __init__(self, action: SignalAction = SignalAction.HOLD, reason: str = ""):
        self.action = action
        self.reason = reason
