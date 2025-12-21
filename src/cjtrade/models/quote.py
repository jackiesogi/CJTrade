from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


@dataclass
class Quote:
    symbol: str
    price: float
    volume: int
    timestamp: str