from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float = 0.0  # Unrealized profit/loss

@dataclass
class Quote:
    symbol: str
    price: float
    volume: int
    timestamp: str

@dataclass
class OrderResult:
    order_id: str
    status: str
    message: str

# connect / disconnect / is_connected /
# get_positions / get_balance / get_quotes /
# place_order / get_broker_name
class BrokerInterface(ABC):
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
    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Get real-time quotes for given symbols.
        Args:
            List of stock symbols

        Returns:
            Dict[str, Quote]
        """
        pass

    @abstractmethod
    def place_order(self, symbol: str, action: str, quantity: int, price: float) -> OrderResult:
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
    def get_broker_name(self) -> str:
        pass