from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List
from .order import Order, OrderStatus, OrderAction
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


from typing import Callable

OrderCallback = Callable[[OrderEvent], None]
FillCallback = Callable[[FillEvent], None]
PriceCallback = Callable[[PriceEvent], None]
TickCallback = Callable[[TickEvent], None]
