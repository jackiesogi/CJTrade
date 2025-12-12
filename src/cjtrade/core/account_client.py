from typing import Dict, Any, List
from enum import Enum
from .brokers.broker_base import BrokerInterface, Position, Quote, OrderResult

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
            from .brokers.sinopac import SinopacBroker
            return SinopacBroker(**config)
        elif broker_type == BrokerType.YUANTA:
            from .brokers.yuanta import YuantaBroker
            return YuantaBroker(**config)
        elif broker_type == BrokerType.CATHAY:
            from .brokers.cathay import CathayBroker
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

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        return self.broker.get_quotes(symbols)

    def place_order(self, symbol: str, action: str, quantity: int, price: float) -> OrderResult:
        return self.broker.place_order(symbol, action, quantity, price)

    def get_broker_name(self) -> str:
        return self.broker.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        return self.broker_type