import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List
from .product import Product

# PARTIALLY ALIGNED WITH SINOPAC
class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CANCEL = "CANCEL"

class PriceType(str, Enum):
    LMT = "LMT"    # 限價單
    MKT = "MKT"    # 市價單
    # STOP = "STOP"  # 停損單

class OrderType(str, Enum):
    ROD = "ROD"    # 當日有效
    IOC = "IOC"    # 立即成交否則取消
    FOK = "FOK"    # 立即全部成交否則取消

class OrderLot(str, Enum):
    IntraDayOdd = "IntraDayOdd"  # 盤中零股
    Common = "Common"            # 一般交易

# TODO: more useful and descriptive status set
# TODO: align with SINOPAC status as much as possible, and add more custom status if needed
class OrderStatus(str, Enum):
    PLACED = "PLACED"         # Order created locally, pending commit (PendingSubmit)
    COMMITTED_WAIT_MARKET_OPEN = "COMMITTED_WAIT_MARKET_OPEN" # PreSubmitted
    COMMITTED_WAIT_MATCHING = "COMMITTED_WAIT_MATCHING"   # Submitted
    FILLED = "FILLED"         # Filled
    PARTIAL = "PARTIAL"       # PartFilled
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"     # Failed
    UNKNOWN = "UNKNOWN"


# PARTIALLY ALIGNED WITH SINOPAC
# order = api.Order(
#     price=17,
#     quantity=3,
#     action=sj.constant.Action.Buy,
#     price_type=sj.constant.StockPriceType.LMT,
#     order_type=sj.constant.OrderType.ROD,
#     order_lot=sj.constant.StockOrderLot.Common,
#     # daytrade_short=False,
#     custom_field="test",
#     account=api.stock_account
# )
@dataclass
class Order:
    product: Product
    action: OrderAction
    price: float
    quantity: int
    price_type: PriceType
    order_type: OrderType
    order_lot: OrderLot

    # Auto generated fields
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # utc+8 time
    created_at: datetime = field(default_factory=lambda: datetime.datetime.utcnow() + datetime.timedelta(hours=8))
    # created_at: datetime = field(default_factory=datetime.datetime.utcnow)

    broker: str = 'na'

    # Optional custom field for broker-specific usage
    opt_field: Dict[str, Any] = field(default_factory=dict)

    # def __str__(self) -> str:
    #     return (f"ID: {self.id} [{self.action}] {self}")


# PARTIALLY ALIGNED WITH SINOPAC
# status = OrderStatus(
#          id='531e27af',
#          status=<Status.PendingSubmit: 'PendingSubmit'>,
#          status_code='00',
#          order_datetime=datetime.datetime(2023, 1, 12, 11, 18, 3, 867490),
#          deals=[]
# )
# @dataclass
# class OrderStatus:
#     id: str
#     status: str
#     code: str
#     order_datetime: datetime.datetime
#     message: str



# NOT ALIGNED WITH SINOPAC
@dataclass
class OrderResult:
    status: OrderStatus
    message: str
    metadata: Dict[str, Any]
    linked_order: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)