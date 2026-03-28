import random
import time
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List

from cjtrade.apps.ArenaX.hist_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.live_backend import ArenaX_Backend_PaperTrade
from cjtrade.apps.ArenaX.none_backend import ArenaX_Backend_None
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.base_broker_api import BrokerAPIBase
from cjtrade.pkgs.db.db_api import *
from cjtrade.pkgs.db.sqlite import *
from cjtrade.pkgs.models.event import *
from cjtrade.pkgs.models.kbar import *
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.position import *
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import *
from cjtrade.pkgs.models.rank_type import RankType
from cjtrade.pkgs.models.trade import *
# from cjtrade.apps.ArenaX.legacy._mock_broker_backend import MockBrokerBackend_Historical
# from cjtrade.apps.ArenaX.legacy._mock_broker_backend import MockBrokerBackend_PaperTrade
# from ._simulation_env import SimulationEnvironment

# MockBrokerAPI will not forward `place_order()` call to the real broker,
# but will fetch data from the real broker if `real_account` is provided.
# In other words, `real_account` is read-only.
class ArenaXBrokerAPI(BrokerAPIBase):
    def __init__(self, **config: Any):
        super().__init__(**config)

        self.real_account = config.get('real_account', None)  # AccountClient instance or None
        self.mock_playback_speed = config.get('speed', 1.0)
        self.backtest_mode = config.get('backtest_mode', True)
        self.backtest_duration = config.get('backtest_duration', 3)
        # Note that state_file is used to persist the mock broker's account state (positions, orders, etc.) across sessions.
        self.state_file = config.get('state_file', "mock_account_state.json")
        if self.backtest_mode == True and self.real_account is not None:
            self.api = ArenaX_Backend_Historical(real_account=self.real_account, playback_speed=self.mock_playback_speed, state_file=self.state_file, num_days_preload=self.backtest_duration)
        elif self.backtest_mode == True and self.real_account is None:
            self.api = ArenaX_Backend_None(state_file=self.state_file, playback_speed=self.mock_playback_speed, num_days_preload=self.backtest_duration)
        else:
            self.api = ArenaX_Backend_PaperTrade(real_account=self.real_account, playback_speed=1.0, state_file=self.state_file)
        self._connected = False

        # db connection
        self.username = config.get('username', 'Ariana')
        self.db_path = config.get('mirror_db_path', f'./data/arenax.db')
        # print(f"ArenaXBroker will use mirror database at: {self.db_path}")
        self.db = None

    def connect(self) -> bool:
        """MockBroker's connection simply starts the simulation environment."""
        try:
            self.api.login()
            self._connected = True
            self.db = connect_sqlite(database=self.db_path)
            prepare_cjtrade_tables(conn=self.db)
            print("ArenaXBroker connected successfully")
            return True
        except Exception as e:
            print(f"ArenaXBroker connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._connected:
            try:
                self.api.logout()
                print("ArenaXBroker disconnected")
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
            datetime=datetime.now(),
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

    def register_order_callback(self, callback: OrderCallback) -> None:
        """
        Placeholder for order callback registration.
        But mock broker is not suitable for using callback mechanism.
        """
        pass

    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        # Mock implementation - return None for simplicity
        # Caller should handle None return value
        return None


    # TODO: Order creation timestamp does not mean Order placing timestamp
    # Actually, the timestamp of when an order was created is not important,
    # instead, the timestamp of when the order was placed (sent to broker) is what matters.
    def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        # Overwrite created_at
        order.created_at = self.api.market.get_market_time()["mock_current_time"]

        res = self.api.place_order(order)

        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        if res.status == OrderStatus.REJECTED:
            update_order_status_to_db(conn=self.db, oid=order.id, status="REJECTED", updated_at=order.created_at)
        return res


    def cancel_order(self, order_id: str) -> OrderResult:
        res = self.api.cancel_order(order_id=order_id)

        update_at = self.api.market.get_market_time()["mock_current_time"]

        if res.status == OrderStatus.CANCELLED:
            update_order_status_to_db(conn=self.db, oid=order_id, status="CANCELLED", updated_at=update_at)

        return res

    def commit_order(self) -> List[OrderResult]:
        res = []
        # Use list() to avoid mutation during iteration
        for otw_odr in list(self.api.account_state.orders_placed):
            update_at = self.api.market.get_market_time()["mock_current_time"]
            update_order_status_to_db(conn=self.db, oid=otw_odr.id, status="COMMITTED_WAIT_MATCHING", updated_at=update_at)
            res.append(self.api.commit_order(otw_odr.id))
        return res

    def list_orders(self) -> List[Trade]:
        return self.api.list_trades()

    def is_market_open(self) -> bool:
        return self.api.market.is_market_open()

    def get_broker_name(self) -> str:
        return "arenax"

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
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common,
            quantity=quantity,
            price=price
        )

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.PLACED:
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
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common,
            quantity=quantity,
            price=price
        )

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.PLACED:
            return [tmp]  # Make sure return in List[OrderResult] format
        else:
            return self.commit_order()


from cjtrade.pkgs.brokers.arenax.arenax_middleware import *
# The version that really connect to the ArenaX standalone server via ArenaXMiddleWare
class ArenaXBrokerAPI_v2(BrokerAPIBase):
    def __init__(self, **config: Any):
        super().__init__(**config)
        self.middleware = ArenaXMiddleWare()
        # self.api = self.middleware
        self.config = config

        # db connection
        self.username = config.get('username', 'Ariana')
        self.db_path = config.get('mirror_db_path', f'./data/arenax.db')
        self.db = None

    def connect(self) -> bool:
        """MockBroker's connection simply starts the simulation environment."""
        try:
            self.middleware.login(self.config['api_key'])
            self._connected = True
            self.db = connect_sqlite(database=self.db_path)
            prepare_cjtrade_tables(conn=self.db)
            print("ArenaXBroker connected successfully")
            return True
        except Exception as e:
            print(f"ArenaXBroker connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._connected:
            try:
                self.middleware.logout()
                print("ArenaXBroker disconnected")
                self.db.close()
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_positions(self) -> List[Position]:
        pos = self.middleware.account_summary().get("positions")
        return [Position(**p) for p in pos]

    def get_balance(self) -> float:
        return float(self.middleware.account_summary().get("balance"))

    # TODO: Move the logic to MockBackend to simulate bid-ask (with time progression)
    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        snapshot = self.middleware.snapshot(product.symbol)
        base_price = snapshot['close'] if snapshot else 100.0

        # TODO: Backend need to query the real bid/ask price rather than simulating one
        return BidAsk(
            symbol=product.symbol,
            datetime=datetime.now(),
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
            snapshot = self.middleware.snapshot(product.symbol)
            snapshot = Snapshot(**snapshot) if snapshot else None
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    # TODO: Call backend to query real kbar rather than using yfinane one in user-side
    def get_kbars(self, product: Product, start: str, end: str, interval: str = "1m"):
        if not self._connected:
            raise ConnectionError("Not connected to simulation environment")

        return None  # TODO: Finish it!
        # # yfinance directly supported intervals
        # yf_supported = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]

        # if interval in yf_supported:
        #     # Direct fetch from yfinance
        #     return self.api.kbars(product.symbol, start, end, interval)
        # else:
        #     # Use internal aggregation for unsupported intervals
        #     kbars_1m = self.api.kbars(product.symbol, start, end, "1m")

        #     if not kbars_1m:
        #         return []

        #     try:
        #         return self.api._aggregate_kbars_internal(kbars_1m, interval)
        #     except ValueError as e:
        #         raise ValueError(f"Mock broker interval '{interval}' not supported: {e}") from e

    def register_order_callback(self, callback: OrderCallback) -> None:
        """
        Placeholder for order callback registration.
        But mock broker is not suitable for using callback mechanism.
        """
        pass

    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        # Mock implementation - return None for simplicity
        # Caller should handle None return value
        return None


    # TODO: Order creation timestamp does not mean Order placing timestamp
    # Actually, the timestamp of when an order was created is not important,
    # instead, the timestamp of when the order was placed (sent to broker) is what matters.
    def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        # Overwrite created_at
        order.created_at = self.get_system_time()["mock_current_time"]

        res = self.middleware.place_order(order)

        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        if res.status == OrderStatus.REJECTED:
            update_order_status_to_db(conn=self.db, oid=order.id, status="REJECTED", updated_at=order.created_at)
        return res


    def cancel_order(self, order_id: str) -> OrderResult:
        res = self.middleware.cancel_order(order_id=order_id)

        update_at = self.get_system_time()["mock_current_time"]

        if res.status == OrderStatus.CANCELLED:
            update_order_status_to_db(conn=self.db, oid=order_id, status="CANCELLED", updated_at=update_at)

        return res

    def commit_order(self) -> List[OrderResult]:
        res = []
        # Use middleware account_summary to find placed orders
        summary = self.middleware.account_summary()
        orders = summary.get("orders", []) if summary else []
        placed_orders = [o for o in orders if o.get("status") == OrderStatus.PLACED.value]
        for o in placed_orders:
            print(f"Committing order {o.get('id') or o.get('order_id') or o.get('ordno')} with status {o.get('status')}")
            order_id = o.get("id") or o.get("order_id") or o.get("ordno")
            try:
                update_at = self.get_system_time()["mock_current_time"]
                update_order_status_to_db(conn=self.db, oid=order_id, status="COMMITTED_WAIT_MATCHING", updated_at=update_at)
                commit_res = self.middleware.commit_order(order_id)
                res.append(commit_res)
            except Exception as e:
                print(f"Error committing order {order_id}: {e}")
        return res

    def list_orders(self) -> List[Trade]:
        odrs = self.middleware.account_summary().get("orders")
        return [Trade(**o) for o in odrs]

    def is_market_open(self) -> bool:
        return self.api.market.is_market_open()

    def get_broker_name(self) -> str:
        return "arenax"

    def get_system_time(self) -> datetime:

        def to_datetime(rfc1223_str):
            return datetime.strptime(rfc1223_str, '%a, %d %b %Y %H:%M:%S %Z')

        t = self.middleware.get_system_time()

        return {
            "mock_current_time": to_datetime(t['mock_current_time']),
            "real_current_time": to_datetime(t['real_current_time']),
            "mock_init_time": to_datetime(t['mock_init_time']),
            "real_init_time": to_datetime(t['real_init_time']),
        }

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
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common,
            quantity=quantity,
            price=price
        )

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.PLACED:
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
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common,
            quantity=quantity,
            price=price
        )

        tmp = self.place_order(order)
        if tmp.status != OrderStatus.PLACED:
            return [tmp]  # Make sure return in List[OrderResult] format
        else:
            return self.commit_order()
