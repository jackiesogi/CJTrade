from enum import Enum
from typing import Any
from typing import Dict
from typing import List

class RankType(str, Enum):
    """Criterion for ranking market movers: percentage change, price change or volume."""
    PRICE_PERCENTAGE_CHANGE = "PRICE_PERCENTAGE_CHANGE"
    PRICE_CHANGE = "PRICE_CHANGE"
    VOLUME = "VOLUME"
