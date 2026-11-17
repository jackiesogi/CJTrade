import uuid
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

from .product import Product

# PARTIALLY ALIGNED WITH SINOPAC
class OrderAction(str, Enum):
    """Side of an order: BUY, SELL or CANCEL."""
    BUY = "BUY"
    SELL = "SELL"
    CANCEL = "CANCEL"

class PriceType(str, Enum):
    """Price type of an order: limit (LMT) or market (MKT)."""
    LMT = "LMT"    # 限價單
    MKT = "MKT"    # 市價單
    # STOP = "STOP"  # 停損單

class OrderType(str, Enum):
    """Common order types (time in force): ROD, IOC, FOK, GTC."""
    ROD = "ROD"    # 當日有效
    IOC = "IOC"    # 立即成交否則取消
    FOK = "FOK"    # 立即全部成交否則取消
    """Not fully supported, depends on broker's actual implementation."""
    GTC = "GTC"    # 長效單（Good Till Cancelled）

class OrderLot(str, Enum):
    """Order lot: intraday odd lot (盤中零股) or common lot (一般交易)."""
    IntraDayOdd = "IntraDayOdd"  # 盤中零股
    Common = "Common"            # 一般交易

# TODO: more useful and descriptive status set
# TODO: align with SINOPAC status as much as possible, and add more custom status if needed
class OrderStatus(str, Enum):
    """Lifecycle status of an order."""
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
    """A CJTrade order for one product.

    Attributes
    ----------
    product : Product
        What to trade.
    action : OrderAction
        BUY or SELL.
    price : float
        Order price.
    quantity : int
        Order quantity.
    price_type : PriceType
        LMT or MKT.
    order_type : OrderType
        Time in force, e.g. ROD.
    order_lot : OrderLot
        Common or intraday odd lot.
    id : str
        CJ order id; a random uuid4 hex by default.
    created_at : datetime
        Creation time as a naive UTC+8 datetime.
    broker : str
        Broker name, ``'na'`` by default.
    opt_field : dict
        Optional broker-specific fields.

    Warnings
    --------
    ``created_at`` defaults to the wall clock (``datetime.utcnow() + 8h``)
    at construction, not to any simulated or replayed time.
    """
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
    created_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=8))
    # created_at: datetime = field(default_factory=datetime.utcnow)

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
    """Result of an order operation reported by a broker client.

    Attributes
    ----------
    status : OrderStatus
        Status after the operation.
    message : str
        Human-readable message from the broker or engine.
    metadata : dict
        Extra broker-specific detail.
    linked_order : str
        Id of the order this result refers to; may be empty.
    id : str
        Result id; a random uuid4 hex by default.
    """
    status: OrderStatus
    message: str
    metadata: Dict[str, Any]
    linked_order: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    def to_dict(self) -> Dict[str, Any]:
        """Return the result as a JSON-friendly dict, with ``status`` as its string value."""
        # Serialize to JSON-friendly dict
        status_val = self.status.value if hasattr(self.status, 'value') else self.status
        return {
            "status": status_val,
            "message": self.message,
            "metadata": self.metadata,
            "linked_order": self.linked_order,
            "id": self.id,
        }
