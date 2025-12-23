import uuid
from enum import Enum
from typing import Any, Dict, List

from cjtrade.brokers.broker_base import *
from cjtrade.models.order import *
from cjtrade.models.position import *
from cjtrade.models.product import *
from cjtrade.models.quote import *


class BrokerType(Enum):
    SINOPAC = "sinopac"  # 永豐金
    YUANTA = "yuanta"    # 元大
    CATHAY = "cathay"    # 國泰


class AccountClient:
    """An unified API to interact with different brokers."""

    def __init__(self, broker_type: BrokerType, **config):
        self.broker_type = broker_type
        self.broker = self._create_broker(broker_type, **config)

    def _create_broker(self, broker_type: BrokerType, **config) -> BrokerInterface:
        if broker_type == BrokerType.SINOPAC:
            from cjtrade.brokers.sinopac.sinopac import SinopacBroker
            return SinopacBroker(**config)
        elif broker_type == BrokerType.YUANTA:
            from cjtrade.brokers.yuanta.yuanta import YuantaBroker
            return YuantaBroker(**config)
        elif broker_type == BrokerType.CATHAY:
            from cjtrade.brokers.cathay.cathay import CathayBroker
            return CathayBroker(**config)
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")

    def connect(self) -> bool:
        return self.broker.connect()

    def disconnect(self) -> None:
        self.broker.disconnect()

    def is_connected(self) -> bool:
        return self.broker.is_connected()

    def get_positions(self) -> List[Position]:
        return self.broker.get_positions()

    def get_balance(self) -> float:
        return self.broker.get_balance()

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, float]:
        return self.broker.get_bid_ask(product, intraday_odd)

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        return self.broker.get_quotes(symbols)

    def place_order(self, order: Order) -> OrderResult:
        return self.broker.place_order(order)

    def commit_order(self, order_id: str) -> OrderResult:
        return self.broker.commit_order(order_id)

    def list_orders(self) -> List[Dict[str, Any]]:
        return self.broker.list_orders()

    def get_broker_name(self) -> str:
        return self.broker.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        return self.broker_type

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        return self.broker.buy_stock(symbol, quantity, price, intraday_odd)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        return self.broker.sell_stock(symbol, quantity, price, intraday_odd)