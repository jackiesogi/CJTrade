# import Dict
from dataclasses import dataclass
from typing import Any
from typing import Dict

@dataclass
class Trade:
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
