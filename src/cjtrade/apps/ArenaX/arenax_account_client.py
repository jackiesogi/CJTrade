import uuid
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

from cjtrade.pkgs.brokers.base_broker_api import *
from cjtrade.pkgs.models.event import *
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.position import *
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import *
from cjtrade.pkgs.models.rank_type import *


class BrokerType(Enum):
    ARENAX  = "arenax"   # 模擬券商 (新)

class AccountState:
    def __init__(self):
        self.positions: List[Position] = []
        self.balance: float = 0.0
        self.last_sync_time: str = ""
        self.pending_orders: List[Order] = [] # Don't implement it for now, too complex.
        self.order_history: List[Order] = []  # Don't implement it for now, too complex.

class ArenaX_AccountClient:
    """An unified API to interact with different brokers."""

    def __init__(self, broker_type: BrokerType, **config):
        self.broker_type = broker_type
        self.broker_api = self._set_broker_api(broker_type, **config)
        self.account_state = AccountState()
        self.broker_api_conn_keepalive = True  # For future use

    def _set_broker_api(self, broker_type: BrokerType, **config) -> BrokerAPIBase:
        if broker_type == BrokerType.ARENAX:
            from cjtrade.apps.ArenaX.arenax_broker_api import ArenaXBrokerAPI
            return ArenaXBrokerAPI(**config)
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")

    def _sync_all(self) -> bool:
        if not self.broker_api.is_connected():
            print("Broker API not connected")
            return False
        self.account_state.balance = self.broker_api.get_balance()
        self.account_state.positions = self.broker_api.get_positions()
        self.account_state.last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def connect(self) -> bool:
        return self.broker_api.connect()

    def disconnect(self) -> None:
        self.broker_api.disconnect()

    def is_connected(self) -> bool:
        return self.broker_api.is_connected()

    def get_positions(self) -> List[Position]:
        self._sync_all()  # will sync `account_state`
        return self.account_state.positions

    def get_balance(self) -> float:
        self._sync_all()  # will sync `account_state`
        return self.account_state.balance

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, float]:
        return self.broker_api.get_bid_ask(product, intraday_odd)

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        return self.broker_api.get_snapshots(products)

    def register_order_callback(self, callback: OrderCallback) -> None:
        return self.broker_api.register_order_callback(callback)

    def get_kbars(self, product: Product, start: str, end: str, interval: str):
        return self.broker_api.get_kbars(product, start, end, interval)

    def get_market_movers(self, top_n: int = 10, by: RankType = RankType.PRICE_PERCENTAGE_CHANGE, ascending: bool = True) -> Dict[str, float]:
        return self.broker_api.get_market_movers(top_n, by, ascending)

    def place_order(self, order: Order) -> OrderResult:
        return self.broker_api.place_order(order)

    def commit_order(self) -> List[OrderResult]:
        return self.broker_api.commit_order()

    def cancel_order(self, order_id: str) -> OrderResult:
        return self.broker_api.cancel_order(order_id)

    def list_orders(self) -> List[Dict[str, Any]]:
        return self.broker_api.list_orders()

    def is_market_open(self) -> bool:
        return self.broker_api.is_market_open()

    def get_broker_name(self) -> str:
        return self.broker_api.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        return self.broker_type

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        return self.broker_api.buy_stock(symbol, quantity, price, intraday_odd)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        return self.broker_api.sell_stock(symbol, quantity, price, intraday_odd)
