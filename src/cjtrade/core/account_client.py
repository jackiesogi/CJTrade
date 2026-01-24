import uuid
from enum import Enum
from typing import Any, Dict, List
from datetime import datetime

from cjtrade.brokers.base_broker_api import *
from cjtrade.models.order import *
from cjtrade.models.position import *
from cjtrade.models.product import *
from cjtrade.models.quote import *
from cjtrade.models.rank_type import *


class BrokerType(Enum):
    SINOPAC = "sinopac"  # 永豐金
    YUANTA = "yuanta"    # 元大
    CATHAY = "cathay"    # 國泰
    MOCK = "mock"        # 模擬券商

class AccountState:
    def __init__(self):
        self.positions: List[Position] = []
        self.balance: float = 0.0
        self.last_sync_time: str = ""
        self.pending_orders: List[Order] = [] # Don't implement it for now, too complex.
        self.order_history: List[Order] = []  # Don't implement it for now, too complex.


# AccountClient = Broker's API (sync source) + AccountState (local cached state)
# For example, when user try to access account balance, AccountClient will:
#   1. Call BrokerAPI to sync the latest state from remote broker server
#   2. Update AccountState with the latest data
#   3. Return the cached balance from AccountState
class AccountClient:
    """An unified API to interact with different brokers."""

    def __init__(self, broker_type: BrokerType, **config):
        self.broker_type = broker_type
        self.broker_api = self._set_broker_api(broker_type, **config)
        self.account_state = AccountState()
        self.broker_api_conn_keepalive = True  # For future use

    def _set_broker_api(self, broker_type: BrokerType, **config) -> BrokerAPIBase:
        if broker_type == BrokerType.SINOPAC:
            from cjtrade.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
            return SinopacBrokerAPI(**config)
        elif broker_type == BrokerType.YUANTA:
            from cjtrade.brokers.yuanta.yuanta import YuantaBrokerAPI
            return YuantaBrokerAPI(**config)
        elif broker_type == BrokerType.CATHAY:
            from cjtrade.brokers.cathay.cathay import CathayBrokerAPI
            return CathayBrokerAPI(**config)
        elif broker_type == BrokerType.MOCK:
            from cjtrade.brokers.mock.mock_broker_api import MockBrokerAPI
            return MockBrokerAPI(**config)
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")

    def _sync_all(self) -> bool:
        self.account_state.balance = self.broker_api.get_balance()
        self.account_state.positions = self.broker_api.get_positions()
        self.account_state.last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # self.account_state.pending_orders = self.broker_api.list_orders()
        # self.account_state.order_history = []


    # Do manually connect if you don't want a lazy connection -> connect when first API call
    def connect(self) -> bool:
        return self.broker_api.connect()

    def disconnect(self) -> None:
        self.broker_api.disconnect()

    def is_connected(self) -> bool:
        return self.broker_api.is_connected()

    def get_positions(self) -> List[Position]:
        if not self.broker_api.is_connected():
            self.broker_api.connect()
        self._sync_all()  # will sync `account_state`
        return self.account_state.positions

    def get_balance(self) -> float:
        if not self.broker_api.is_connected():
            self.broker_api.connect()
        self._sync_all()  # will sync `account_state`
        return self.account_state.balance

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, float]:
        return self.broker_api.get_bid_ask(product, intraday_odd)

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        return self.broker_api.get_snapshots(products)

    def get_kbars(self, product: Product, start: str, end: str, interval: str):
        # note that the range is [start,end), end is exclusive.
        # TODO: test each interval aggregation stability (especially edge cases)
        # interval: '1m', '3m', '5m', '10m', '15m', '20m', '30m', '45m',
        #           '1h', '90m', '2h', '1d', '1w', '1M'
        return self.broker_api.get_kbars(product, start, end, interval)

    def get_market_movers(self, top_n: int = 10, by: RankType = RankType.PRICE_PERCENTAGE_CHANGE, ascending: bool = True) -> Dict[str, float]:
        return self.broker_api.get_market_movers(top_n, by, ascending)

    # TODO: Cache order data locally in AccountState
    def place_order(self, order: Order) -> OrderResult:
        return self.broker_api.place_order(order)

    # TODO: Cache order data locally in AccountState
    def commit_order(self) -> List[OrderResult]:
        return self.broker_api.commit_order()

    # TODO: Plan to remove in next minor version
    # def commit_order_legacy(self, order_id: str) -> OrderResult:
    #     return self.broker_api.commit_order_legacy(order_id)

    # TODO: Cache order data locally in AccountState
    def cancel_order(self, order_id: str) -> OrderResult:
        return self.broker_api.cancel_order(order_id)

    # TODO: Cache order data locally in AccountState
    def list_orders(self) -> List[Dict[str, Any]]:
        return self.broker_api.list_orders()

    def get_broker_name(self) -> str:
        return self.broker_api.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        return self.broker_type

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        return self.broker_api.buy_stock(symbol, quantity, price, intraday_odd)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        return self.broker_api.sell_stock(symbol, quantity, price, intraday_odd)