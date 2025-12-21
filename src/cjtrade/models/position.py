from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float = 0.0  # Unrealized profit/loss