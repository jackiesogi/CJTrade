from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from .order import Order
from .order import OrderAction
from .order import OrderStatus
from .product import Product


class EventType(str, Enum):
    ORDER_STATUS_CHANGE = "ORDER_STATUS_CHANGE"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    PRICE_CHANGE = "PRICE_CHANGE"
    TICK = "TICK"


@dataclass
class OrderEvent:
    """
    Example:
        ```python
        def on_order_change(event: OrderEvent):
            print(f"Order {event.order_id} status: {event.old_status} -> {event.new_status}")
            if event.new_status == OrderStatus.FILLED:
                print(f"Order filled! Total: {event.filled_quantity} @ {event.filled_price}")

        client.register_order_callback(on_order_change)
        ```
    """
    event_type: EventType
    timestamp: datetime
    order_id: str
    symbol: str
    action: OrderAction
    quantity: int
    price: float

    old_status: OrderStatus
    new_status: OrderStatus

    filled_quantity: int = 0
    filled_price: Optional[float] = None
    filled_value: Optional[float] = None  # filled_quantity * filled_price

    order: Optional[Order] = None

    broker_raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)

    message: str = ""

    def is_filled(self) -> bool:
        return self.new_status in [OrderStatus.FILLED, OrderStatus.PARTIAL]

    def is_completely_filled(self) -> bool:
        return self.new_status == OrderStatus.FILLED

    def is_cancelled(self) -> bool:
        return self.new_status == OrderStatus.CANCELLED

    def is_rejected(self) -> bool:
        return self.new_status == OrderStatus.REJECTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value if hasattr(self.event_type, 'value') else self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action.value if hasattr(self.action, 'value') else self.action,
            "quantity": self.quantity,
            "price": self.price,
            "old_status": self.old_status.value if hasattr(self.old_status, 'value') else self.old_status,
            "new_status": self.new_status.value if hasattr(self.new_status, 'value') else self.new_status,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "filled_value": self.filled_value,
            "message": self.message,
        }


@dataclass
class FillEvent:
    """
    Example:
        ```python
        def on_fill(event: FillEvent):
            print(f"✅ {event.action} {event.filled_quantity} {event.symbol} @ {event.filled_price}")

            if event.symbol == "0050" and event.filled_quantity >= 100:
                hedge_order = create_hedge_order(event)
                client.place_order(hedge_order)

        client.register_fill_callback(on_fill)
        ```
    """
    timestamp: datetime
    order_id: str
    symbol: str
    action: OrderAction

    filled_quantity: int
    filled_price: float
    filled_value: float

    total_filled_quantity: int
    remaining_quantity: int

    order_status: OrderStatus    # PARTIAL or FILLED

    fill_sequence: int = 1

    deal_id: Optional[str] = None

    order: Optional[Order] = None

    broker_raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)

    def is_complete_fill(self) -> bool:
        return self.order_status == OrderStatus.FILLED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action.value if hasattr(self.action, 'value') else self.action,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "filled_value": self.filled_value,
            "total_filled_quantity": self.total_filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "order_status": self.order_status.value if hasattr(self.order_status, 'value') else self.order_status,
            "fill_sequence": self.fill_sequence,
            "deal_id": self.deal_id,
        }


@dataclass
class PriceEvent:
    """
    Example:
        ```python
        def on_price_alert(event: PriceEvent):
            if event.symbol == "2330" and event.current_price > event.threshold:
                print(f"⚠️ {event.symbol} over {event.threshold}!")
                order = create_breakout_order(event.symbol)
                client.place_order(order)

        client.register_price_callback(on_price_alert, symbol="2330", threshold=600)
        ```
    """
    timestamp: datetime
    symbol: str
    current_price: float
    previous_price: Optional[float] = None

    condition_type: str = ""  # "ABOVE", "BELOW", "CHANGE_PERCENT", "TIME_INTERVAL"
    threshold: Optional[float] = None

    price_change: Optional[float] = None
    price_change_percent: Optional[float] = None

    volume: Optional[int] = None
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None

    broker_raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "current_price": self.current_price,
            "previous_price": self.previous_price,
            "condition_type": self.condition_type,
            "threshold": self.threshold,
            "price_change": self.price_change,
            "price_change_percent": self.price_change_percent,
            "volume": self.volume,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
        }


@dataclass
class TickEvent:
    """
    Example:
        ```python
        tick_buffer = []

        def on_tick(event: TickEvent):
            tick_buffer.append(event)

            if len(tick_buffer) >= 10:
                avg_price = sum(t.price for t in tick_buffer) / 10
                print(f"10 avg: {avg_price}")
                tick_buffer.clear()

        client.register_tick_callback(on_tick, symbol="0050")
        ```
    """
    timestamp: datetime
    symbol: str
    price: float
    volume: int

    tick_type: str = ""  # "BUY", "SELL", "NEUTRAL"

    broker_raw_data: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "volume": self.volume,
            "tick_type": self.tick_type,
        }


from typing import Callable

OrderCallback = Callable[[OrderEvent], None]
FillCallback = Callable[[FillEvent], None]
PriceCallback = Callable[[PriceEvent], None]
TickCallback = Callable[[TickEvent], None]
