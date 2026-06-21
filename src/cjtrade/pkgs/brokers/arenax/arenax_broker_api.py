"""
Name:
  ArenaX Broker API v2
Description:
  User-side API that commnunicates with the ArenaX (Simulated Broker) via ArenaXMiddleWare.
Usecase:
  Perform trading operations and account operations in the ArenaX simulated environment,
  such as placing/canceling orders, querying account cash balance, positions and market
  stock prices, etc.

Code quality check:
- todo       : 2026-05-01
- note       : 2026-05-01
- code logic : 2026-05-01
- dead code  : 2026-05-01
"""
import os
import random
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List

from cjtrade.pkgs.brokers.arenax.arenax_middleware import ArenaXMiddleWare
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


class ArenaXBrokerAPI_v2(BrokerAPIBase):
    """Broker API that communicates with the ArenaX standalone server via ArenaXMiddleWare.

    For unit tests, inject a mock middleware via the `middleware` keyword argument:
        api = ArenaXBrokerAPI_v2(middleware=MockMiddleWare())
    """
    def __init__(self, **config: Any):
        super().__init__(**config)
        self.host = config.get('arenax_host', 'localhost')
        _default_port = int(os.environ.get('ARENAX_PORT', 8801))
        self.port = config.get('arenax_port', _default_port)
        self.middleware: ArenaXMiddleWare = config.get('middleware') or \
        ArenaXMiddleWare(
            host=self.host,
            port=self.port
        )
        self.config = config

        # db connection
        self.username = config.get('username', 'Ariana')
        self.db_path = config.get('mirror_db_path', f'./data/arenax.db')
        self.db = None


    def connect(self) -> bool:
        """Connect to the ArenaX standalone server via ArenaXMiddleWare
            and set up the local SQLite mirror database.
            Returns True if connection is successful, False otherwise.
        """
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
            snapshot = Snapshot.from_dict(snapshot) if snapshot else None
            if snapshot:
                snapshots.append(snapshot)

        return snapshots


    # TODO: Call backend to query real kbar rather than using yfinane one in user-side
    def get_kbars(self, product: Product, start: str, end: str, interval: str = "1m"):
        # Note: kbar fetching is a read-only data operation and does not require
        # an authenticated trading session.  No _connected guard here.

        supported_intervals = ["1m", "5m", "1h", "1d"]
        if interval not in supported_intervals:
            print(f"Interval '{interval}' not supported by backend broker API, using '1m'")
            interval = "1m"

        # Server selects the data source automatically (price_db → real broker → yfinance).
        # No client-side availability check or fallback routing needed.
        kbars_raw = self.middleware.get_kbars(product.symbol, start, end, interval)

        def _parse_kbar(kr: dict) -> Kbar:
            ts = kr["timestamp"]
            if isinstance(ts, str):
                from datetime import datetime as _dt
                try:
                    ts = _dt.fromisoformat(ts)
                except ValueError:
                    ts = _dt.strptime(ts, "%a, %d %b %Y %H:%M:%S GMT")
            return Kbar(
                timestamp=ts,
                open=float(kr["open"]),
                high=float(kr["high"]),
                low=float(kr["low"]),
                close=float(kr["close"]),
                volume=int(kr["volume"]),
            )

        kbars = [_parse_kbar(kr) for kr in kbars_raw] if kbars_raw else []

        return kbars


    # TODO: Finish this!
    def register_order_callback(self, callback: OrderCallback) -> None:
        """
        Placeholder for order callback registration.
        But mock broker is not suitable for using callback mechanism.
        """
        pass


    # TODO: Finish this!
    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        # Mock implementation - return None for simplicity
        # Caller should handle None return value
        return None


    def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        if order.order_type == OrderType.GTC:
            raise NotImplementedError("GTC orders are not yet supported in ArenaX")

        # Overwrite created_at (place ts is much more important than create ts)
        order.created_at = self.get_system_time()["mock_current_time"]

        res = self.middleware.place_order(order)

        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        # insert_new_order_to_db always writes 'PLACED'; update to actual status immediately
        update_order_status_to_db(conn=self.db, oid=order.id, status=res.status.value, updated_at=order.created_at)
        return res


    def cancel_order(self, order_id: str) -> OrderResult:
        res = self.middleware.cancel_order(order_id=order_id)

        update_at = self.get_system_time()["mock_current_time"]

        if res.status == OrderStatus.CANCELLED:
            update_order_status_to_db(conn=self.db, oid=order_id, status="CANCELLED", updated_at=update_at)

        return res


    def sync_state(self) -> List[OrderResult]:
        """Refresh status of all committed orders from the broker backend."""
        res = []
        summary = self.middleware.account_summary()
        orders = summary.get("orders", []) if summary else []
        committed_statuses = {OrderStatus.COMMITTED_WAIT_MATCHING.value, OrderStatus.COMMITTED_WAIT_MARKET_OPEN.value}
        committed_orders = [o for o in orders if o.get("status") in committed_statuses]
        for o in committed_orders:
            order_id = o.get("id") or o.get("order_id") or o.get("ordno")
            try:
                refreshed = self.middleware.sync_state(order_id)
                if refreshed:
                    update_at = self.get_system_time()["mock_current_time"]
                    update_order_status_to_db(conn=self.db, oid=order_id, status=refreshed.status.value, updated_at=update_at)
                    res.append(refreshed)
            except Exception as e:
                print(f"Error refreshing order {order_id}: {e}")
        return res


    def list_orders(self) -> List[Trade]:
        odrs = self.middleware.account_summary().get("orders")
        return [Trade(**o) for o in odrs]


    def is_market_open(self) -> bool:
        return self.middleware.is_market_open()


    def get_broker_name(self) -> str:
        return f"arenax ({self.port})"


    def get_market_time(self) -> dict:
        return self.get_system_time()


    # 所有 datetime 在 JSON 邊界都用 .isoformat() 序列化
    # 接收方用 fromisoformat() 反序列化 任何地方不做 timezone 轉換!!
    # 所有 datetime 都是 隱性台北時間的 naive datetime
    def get_system_time(self) -> dict:
        # Server emits all datetime fields as ISO 8601 (naive Asia/Taipei).
        # Parse with fromisoformat(); no timezone conversion needed.
        t = self.middleware.get_system_time()
        return {
            "mock_current_time": datetime.fromisoformat(t['mock_current_time']),
            "real_current_time": datetime.fromisoformat(t['real_current_time']),
            "mock_init_time":    datetime.fromisoformat(t['mock_init_time']),
            "real_init_time":    datetime.fromisoformat(t['real_init_time']),
        }


    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
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
            price=price,
            opt_field=opt_field or {},
        )

        return self.place_order(order)


    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
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
            price=price,
            opt_field=opt_field or {},
        )

        return self.place_order(order)
