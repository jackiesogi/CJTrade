from typing import Any, Dict, List
import time
import random
from datetime import datetime
from cjtrade.brokers.broker_base import BrokerInterface
from cjtrade.models.order import *
from cjtrade.models.position import *
from cjtrade.models.product import *
from cjtrade.models.quote import *
from cjtrade.core.account_client import AccountClient
from ._simulation_env import SimulationEnvironment


class MockBroker(BrokerInterface):
    def __init__(self, **config: Any):
        super().__init__(**config)

        self.real_account = config.get('real_account', None)  # AccountClient instance or None
        self._simulation = SimulationEnvironment(real_account=self.real_account)
        self._connected = False

    def connect(self) -> bool:
        """MockBroker's connection simply starts the simulation environment."""
        try:
            self._simulation.start()
            self._connected = True
            print("MockBroker connected successfully")
            return True
        except Exception as e:
            print(f"MockBroker connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._connected:
            try:
                self._simulation.stop()
                print("MockBroker disconnected")
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_positions(self) -> List[Position]:
        return self._simulation.positions

    def get_balance(self) -> float:
        return self._simulation.get_account_balance()

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        snapshot = self._simulation.get_dummy_snapshot(product.symbol)
        base_price = snapshot.close if snapshot else 100.0

        return BidAsk(
            symbol=product.symbol,
            datetime=datetime.datetime.now(),
            bid_price=[base_price - i*0.5 for i in range(5)],
            bid_volume=[random.randint(50, 500) for _ in range(5)],
            ask_price=[base_price + 0.5 + i*0.5 for i in range(5)],
            ask_volume=[random.randint(50, 500) for _ in range(5)]
        )

    # TODO: Plan to remove
    # def get_quotes(self, products: List[Product]) -> Dict[str, Quote]:
    #     if not self._connected:
    #         raise ConnectionError("Not connected to broker")

    #     quotes = {}
    #     for product in products:
    #         snapshot = self._simulation.get_dummy_snapshot(product.symbol)
    #         if snapshot:
    #             quotes[product.symbol] = Quote(
    #                 symbol=product.symbol,
    #                 price=snapshot.close,
    #                 volume=snapshot.volume,
    #                 timestamp=snapshot.timestamp.isoformat()
    #             )

    #     return quotes

    # Note: This actually returns a 1-min kbar
    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        snapshots = []
        for product in products:
            snapshot = self._simulation.get_dummy_snapshot(product.symbol)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        timestamp = int(time.time() * 1000)
        random_num = random.randint(1000, 9999)
        order_id = f"mock_order_{timestamp}_{random_num}"

        return OrderResult(
            status=OrderStatus.ON_THE_WAY,
            message="Mock order placed successfully",
            metadata={},
            linked_order=order.id
        )

    def commit_order(self) -> OrderResult:
        return OrderResult(
            status=OrderStatus.ON_THE_WAY,
            linked_order="0xDEADF00D",  # TODO: implement a id-obj mapping to be able to track
            metadata={},
            message="Mock order committed successfully"
        )

    def list_orders(self) -> List[Dict]:
        return []

    def get_broker_name(self) -> str:
        return "mock_securities"

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )

        order = Order(
            product=product,
            action=OrderAction.BUY,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=intraday_odd,
            quantity=quantity,
            price=price
        )

        return self.place_order(order)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )

        order = Order(
            product=product,
            action=OrderAction.SELL,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=intraday_odd,
            quantity=quantity,
            price=price
        )

        return self.place_order(order)