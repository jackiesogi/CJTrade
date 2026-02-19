from typing import Any, Dict, List
import time
import random
from datetime import datetime

from cjtrade.brokers.base_broker_api import BrokerAPIBase
from cjtrade.models.order import *
from cjtrade.models.position import *
from cjtrade.models.product import *
from cjtrade.models.quote import *
from cjtrade.models.kbar import *
from cjtrade.models.trade import *
from cjtrade.core.account_client import AccountClient
from cjtrade.db.db_api import *
from cjtrade.db.sqlite import *
# from ._simulation_env import SimulationEnvironment
from cjtrade.models.rank_type import RankType
from ._mock_broker_backend import MockBrokerBackend

# MockBrokerAPI will not forward `place_order()` call to the real broker,
# but will fetch data from the real broker if `real_account` is provided.
# In other words, `real_account` is read-only.
class MockBrokerAPI(BrokerAPIBase):
    def __init__(self, **config: Any):
        super().__init__(**config)

        self.real_account = config.get('real_account', None)  # AccountClient instance or None
        self.mock_playback_speed = config.get('speed', 1.0)
        self.state_file = config.get('state_file', "mock_account_state.json")
        self.api = MockBrokerBackend(real_account=self.real_account, playback_speed=self.mock_playback_speed, state_file=self.state_file)
        self._connected = False

        # db connection
        self.username = config.get('username', 'user000')
        self.db = config.get('mirror_db_path', f'./data/mock.db')

    def connect(self) -> bool:
        """MockBroker's connection simply starts the simulation environment."""
        try:
            self.api.login()
            self._connected = True
            print("MockBroker connected successfully")
            self.db = connect_sqlite(database=self.db)
            prepare_cjtrade_tables(conn=self.db)
            return True
        except Exception as e:
            print(f"MockBroker connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._connected:
            try:
                self.api.logout()
                print("MockBroker disconnected")
                self.db.close()
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_positions(self) -> List[Position]:
        return self.api.list_positions()

    def get_balance(self) -> float:
        return self.api.account_balance()

    # TODO: Move the logic to MockBackend to simulate bid-ask (with time progression)
    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        snapshot = self.api.snapshot(product.symbol)
        base_price = snapshot.close if snapshot else 100.0

        return BidAsk(
            symbol=product.symbol,
            datetime=datetime.datetime.now(),
            bid_price=[base_price - i*0.5 for i in range(5)],
            bid_volume=[random.randint(50, 500) for _ in range(5)],
            ask_price=[base_price + 0.5 + i*0.5 for i in range(5)],
            ask_volume=[random.randint(50, 500) for _ in range(5)]
        )


    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        snapshots = []
        for product in products:
            snapshot = self.api.snapshot(product.symbol)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    def get_kbars(self, product: Product, start: str, end: str, interval: str = "1m"):
        if not self._connected:
            raise ConnectionError("Not connected to simulation environment")

        # yfinance directly supported intervals
        yf_supported = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]

        if interval in yf_supported:
            # Direct fetch from yfinance
            return self.api.kbars(product.symbol, start, end, interval)
        else:
            # Use internal aggregation for unsupported intervals
            kbars_1m = self.api.kbars(product.symbol, start, end, "1m")

            if not kbars_1m:
                return []

            try:
                return self.api._aggregate_kbars_internal(kbars_1m, interval)
            except ValueError as e:
                raise ValueError(f"Mock broker interval '{interval}' not supported: {e}") from e

    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        # Mock implementation - return None for simplicity
        # Caller should handle None return value
        return None


    # TODO: Order creation timestamp does not mean Order placing timestamp
    def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        res = self.api.place_order(order)

        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        if res.status == OrderStatus.REJECTED:
            update_order_status_to_db(conn=self.db, oid=order.id, status="REJECTED")
        return res


    def cancel_order(self, order_id: str) -> OrderResult:
        res = self.api.cancel_order(order_id=order_id)

        if res.status == OrderStatus.CANCELLED:
            update_order_status_to_db(conn=self.db, oid=order_id, status="CANCELLED")

        return res

    def commit_order(self) -> List[OrderResult]:
        res = []
        # Use list() to avoid mutation during iteration
        for otw_odr in list(self.api.account_state.orders_placed):
            update_order_status_to_db(conn=self.db, oid=otw_odr.id, status="COMMITTED")
            res.append(self.api.commit_order(otw_odr.id))
        return res


    # TODO: Plan to remove in next minor version
    # def commit_order_legacy(self, order_id: str) -> OrderResult:
    #     return OrderResult(
    #         status=OrderStatus.COMMITTED,
    #         # linked_order="0xDEADF00D",
    #         linked_order=order_id,  # TODO: implement a id-obj mapping to be able to track
    #         metadata={},
    #         message="Mock order committed successfully"
    #     )

    def list_orders(self) -> List[Trade]:
        return self.api.list_trades()

    def get_broker_name(self) -> str:
        return "mock"

    def get_system_time(self) -> datetime:
        return self.api.market.get_market_time()['mock_current_time']

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
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

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.ON_THE_WAY:
            return [tmp]  # Make sure return in List[OrderResult] format
        else:
            return self.commit_order()

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
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

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.ON_THE_WAY:
            return [tmp]  # Make sure return in List[OrderResult] format
        else:
            return self.commit_order()