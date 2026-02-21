from abc import ABC, abstractmethod
from typing import Any, Dict, List

from cjtrade.models.order import *
from cjtrade.models.position import *
from cjtrade.models.product import *
from cjtrade.models.quote import *
from cjtrade.models.kbar import *

# connect / disconnect / is_connected /
# get_positions / get_balance / get_quotes /
# place_order / get_broker_name
class BrokerAPIBase(ABC):
    """
    An unified interface for different brokers.
    All broker implementations must inherit from
    this class and implement all abstract methods.
    """
    def __init__(self, **config: Any):
        self.config = config

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Get current stock positions.

        Returns:
            List[Position]
        """
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """Get account balance.

        Returns:
            float: account balance
        """
        pass

    @abstractmethod
    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        pass

    @abstractmethod
    def get_kbars(self, products: List[Product], start: str, end: str, interval: str) -> List[Kbar]:
        """
        return a list of Kbar, 1-min kbar by default
        note that the range is [start,end), end is exclusive.
        """
        pass

    @abstractmethod
    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """
        Get real-time market snapshots for given products.
        It must contain more detail than `get_quotes()`/ `get_bid_ask()` does.
        If broker's api does not provide some fields that required by `Snapshot`,
        broker must mention them in the `additional_note`.
        """
        pass

    # @abstractmethod  # TODO: Un-comment this when implementation is done
    # Event:
    # - time_period (e.g. every 15 sec)
    # - price_change (e.g. +1% change) 
    # - fill_period (e.g. every 100 trade ticks) 
    # - volume_thresh (e.g. more than 100 shares traded)
    def register_price_callback():
        """
        Define what things to do when a certain price event happens.
        """
        pass

    # @abstractmethod  # TODO: Un-comment this when implementation is done
    def register_fill_callback():
        """
        Define what things to do when a certain order fill event happens.
        """
        pass

    # @abstractmethod  # TODO: Un-comment this when implementation is done
    def unregister_callback():
        pass

    @abstractmethod
    def place_order(self, order: Order) -> OrderResult:
        """
        Args:
            symbol
            action
            quantity
            price

        Returns:
            OrderResult
        """
        pass

    @abstractmethod
    def commit_order(self) -> OrderResult:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult:
        pass

    @abstractmethod
    def list_orders(self) -> List[Dict]:
        pass

    @abstractmethod
    def get_broker_name(self) -> str:
        pass

    ##### SIMPLE HIGH-LEVEL METHODS #####
    @abstractmethod
    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        pass

    @abstractmethod
    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
        pass