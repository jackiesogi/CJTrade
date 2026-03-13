from dataclasses import dataclass

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
