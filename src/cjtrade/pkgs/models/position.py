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
