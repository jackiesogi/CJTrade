from enum import Enum
from typing import Any
from typing import Dict
from typing import List

class RankType(str, Enum):
    PRICE_PERCENTAGE_CHANGE = "PRICE_PERCENTAGE_CHANGE"
    PRICE_CHANGE = "PRICE_CHANGE"
    VOLUME = "VOLUME"
