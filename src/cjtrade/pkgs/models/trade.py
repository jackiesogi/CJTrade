# import Dict
from dataclasses import dataclass
from typing import Any
from typing import Dict

@dataclass
class Trade:
    """An order as reported back by a broker, with its status and deal count.

    Attributes
    ----------
    id : str
        Order id.
    symbol : str
        Ticker.
    action, status, order_type, price_type : str
        String forms of the order's enums.
    quantity : int
        Order quantity.
    price : float
        Order price.
    order_lot : int
        Order lot.
    order_datetime : str
        Time the order was placed.
    deals : int
        Number of deals (fills) so far.
    ordno : str
        Broker order number.
    """
    id: str
    symbol: str
    action: str
    quantity: int
    price: float
    status: str
    order_type: str
    price_type: str
    order_lot: int
    order_datetime: str
    deals: int
    ordno: str

    def to_dict(self) -> Dict[str, Any]:
        """Return the trade as a dict."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status,
            "order_type": self.order_type,
            "price_type": self.price_type,
            "order_lot": self.order_lot,
            "order_datetime": self.order_datetime,
            "deals": self.deals,
            "ordno": self.ordno,
        }
