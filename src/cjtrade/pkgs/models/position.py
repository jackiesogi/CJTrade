from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float = 0.0  # Unrealized profit/loss

    def __str__(self) -> str:
        return (f"Hold {self.quantity * 1000} shares of {self.symbol} with avg cost {self.avg_cost}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
        }
