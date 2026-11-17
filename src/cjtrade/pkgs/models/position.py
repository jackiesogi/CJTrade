from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

@dataclass
class Position:
    """A held position in one symbol.

    Attributes
    ----------
    symbol : str
        Ticker.
    quantity : int
        Held quantity; ``__str__`` reports it as ``quantity * 1000`` shares.
    avg_cost : float
        Average cost.
    current_price : float
        Latest price.
    market_value : float
        Current market value.
    unrealized_pnl : float
        Unrealized profit/loss; 0.0 by default.
    """
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float = 0.0  # Unrealized profit/loss

    def __str__(self) -> str:
        return (f"Hold {self.quantity * 1000} shares of {self.symbol} with avg cost {self.avg_cost}")

    def to_dict(self) -> Dict[str, Any]:
        """Return the position as a dict."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
        }
