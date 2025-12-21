from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


class Exchange(str, Enum):
    TSE = "TSE"
    # to be added (e.g., OTC, NYSE, NASDAQ, etc.)


class ProductType(str, Enum):
    STOCK = "Stocks"
    # ETF = "ETF"
    # REIT = "REIT"
    # BOND = "BOND"
    # OPTION = "OPTION"
    # FUTURE = "FUTURE"
    # FOREX = "FOREX"

# NOT ALIGNED WITH SINOPAC!!!
# contract=Stock(
#         exchange=<Exchange.TSE: 'TSE'>,
#         code='2890',
#         symbol='TSE2890',
#         name='永豐金',
#         category='17',
#         unit=1000,
#         limit_up=19.05,
#         limit_down=15.65,
#         reference=17.35,
#         update_date='2023/01/12',
#         day_trade=<DayTrade.Yes: 'Yes'>
# )
# {ProductType}.{Exchange}.{Symbol}
@dataclass(frozen=True)  # Note that Product == Contract == 標的
class Product:
    symbol: str
    type: ProductType = ProductType.STOCK
    exchange: str = Exchange.TSE
    category: str = ""
    tags: List[str] = None
    metadata: Dict[str, Any] = None