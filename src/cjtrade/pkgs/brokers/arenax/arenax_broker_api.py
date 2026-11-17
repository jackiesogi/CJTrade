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

from cjtrade.pkgs import paths
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

    Parameters
    ----------
    **config
        ``arenax_host`` (default ``'localhost'``), ``arenax_port`` (default
        ``$ARENAX_PORT`` or 8801), ``middleware``, ``api_key`` (needed by
        connect()), ``username`` (default ``'Ariana'``) and
        ``mirror_db_path``.
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
        self.db_path = config.get('mirror_db_path') or str(paths.mirror_db_path('arenax'))
        self.db = None


    def connect(self) -> bool:
        """Connect to the ArenaX standalone server and set up the local SQLite mirror database.

        Logs in via ArenaXMiddleWare.

        Returns
        -------
        bool
            True if connection is successful, False otherwise.

        Warnings
        --------
        Makes a network call and opens (creating if needed) the mirror database file.
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
        """Log out of the server and close the mirror database.

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
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
        """Return whether connect() succeeded and disconnect() has not been called.

        Returns
        -------
        bool

        Warnings
        --------
        Raises AttributeError if called before connect(); disconnect() does too.
        """
        return self._connected


    def _account_summary(self) -> dict:
        """The account, or a ConnectionError naming what went wrong.

        ArenaXMiddleWare swallows every transport failure and returns None, so
        a timeout, a refused connection or a restarting server all arrived here
        as None and then became `AttributeError: 'NoneType' object has no
        attribute 'get'` two frames further in -- which says nothing about the
        broker being unreachable, and which no caller was ever going to catch
        by name.

        Not a default: an unanswered read is not a balance of 0.0 and not an
        empty position list. Either one of those would be acted on -- 0.0 trips
        the engine's loss limit, and no positions makes a held symbol look
        available to buy again.
        """
        summary = self.middleware.account_summary()
        if summary is None:
            raise ConnectionError(
                f"ArenaX server at {self.host}:{self.port} did not answer "
                f"GET /api/v1/account")
        return summary


    def get_positions(self) -> List[Position]:
        """Return current positions from the server.

        Returns
        -------
        List[Position]

        Raises
        ------
        ConnectionError
            The server did not answer.

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
        pos = self._account_summary().get("positions")
        return [Position(**p) for p in (pos or [])]


    def get_balance(self) -> float:
        """Return the account balance from the server.

        Returns
        -------
        float

        Raises
        ------
        ConnectionError
            The server did not answer or sent no balance.

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
        balance = self._account_summary().get("balance")
        if balance is None:
            raise ConnectionError(
                f"ArenaX server at {self.host}:{self.port} answered "
                f"GET /api/v1/account with no balance")
        return float(balance)


    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        """Return a simulated five-level bid/ask quote for a product.

        Parameters
        ----------
        product : Product
        intraday_odd : bool, optional
            Accepted for interface compatibility; not used.

        Returns
        -------
        BidAsk

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Not real quotes: prices are spaced 0.5 around the last close (100.0 if
        no snapshot), volumes are random, and the timestamp is the local wall clock.
        """
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
        """Return snapshots for the given products.

        Products the server returns no snapshot for are skipped.

        Parameters
        ----------
        products : List[Product]

        Returns
        -------
        List[Snapshot]

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
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
        """Return kbars for a product from the ArenaX server.

        Does not require connect().

        Parameters
        ----------
        product : Product
        start : str
            Start date.
        end : str
            End date, exclusive.
        interval : str, optional
            '1m', '5m', '1h' or '1d'. Any other value prints a message and
            falls back to '1m'.

        Returns
        -------
        List[Kbar]

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
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
                # Server response has no code field; take it from the request.
                symbol=kr.get("symbol") or product.symbol,
            )

        kbars = [_parse_kbar(kr) for kr in kbars_raw] if kbars_raw else []

        return kbars


    # TODO: Finish this once the server grows GET /api/v1/events.
    def register_order_callback(self, callback: OrderCallback) -> None:
        """Not implemented. Poll sync_state() or list_orders() instead.

        A callback is a local function, so there is nothing to register with a
        REST server -- the server-side shape for this is an append-only event
        log the client tails:

            GET /api/v1/events?after=<seq>  ->  {"events": [...], "last_seq": N}

        and THIS method is where the callback illusion gets manufactured: store
        `callback`, run a daemon thread that tails the log, rebuild each
        OrderEvent and invoke it. The server would learn nothing about
        callbacks, and the backend would only append to the log from the two
        places that already own every transition -- _apply_fill() and the
        cancel path.

        Warnings
        --------
        Placeholder: always raises NotImplementedError.
        """
        raise NotImplementedError(
            "ArenaX has no push callback yet; poll sync_state() or list_orders()."
        )


    # TODO: Finish this!
    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        """Not implemented; returns None.

        Warnings
        --------
        Placeholder: always returns None.
        """
        # Mock implementation - return None for simplicity
        # Caller should handle None return value
        return None


    def place_order(self, order: Order) -> OrderResult:
        """Place an order on the ArenaX server and record it in the mirror database.

        Sets ``order.created_at`` to the current market time before sending.

        Parameters
        ----------
        order : Order

        Returns
        -------
        OrderResult

        Raises
        ------
        ConnectionError
            Not connected, or the server did not answer.
        ValueError
            The server rejected the order.

        Warnings
        --------
        Makes a network call (simulated order, not a real one) and writes the
        order to the local mirror database.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        # Overwrite created_at (place ts is much more important than create ts)
        order.created_at = self.get_market_time()["mock_current_time"]

        res = self.middleware.place_order(order)

        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        # insert_new_order_to_db always writes 'PLACED'; update to actual status immediately
        update_order_status_to_db(conn=self.db, oid=order.id, status=res.status.value, updated_at=order.created_at)
        return res


    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order on the ArenaX server.

        The mirror database is updated only when the result is CANCELLED.

        Parameters
        ----------
        order_id : str
            The CJTrade order id.

        Returns
        -------
        OrderResult

        Raises
        ------
        ConnectionError
            The server did not answer.

        Warnings
        --------
        Makes network calls and writes to the local mirror database.
        """
        res = self.middleware.cancel_order(order_id=order_id)

        update_at = self.get_market_time()["mock_current_time"]

        if res.status == OrderStatus.CANCELLED:
            update_order_status_to_db(conn=self.db, oid=order_id, status="CANCELLED", updated_at=update_at)

        return res


    def sync_state(self) -> List[OrderResult]:
        """Refresh status of all committed orders from the broker backend.

        Returns
        -------
        List[OrderResult]
            One result per refreshed order. Per-order errors are printed and
            skipped.

        Warnings
        --------
        Makes network calls and writes order status to the local mirror database.
        """
        res = []
        orders = self.middleware.list_orders()
        committed_statuses = {OrderStatus.COMMITTED_WAIT_MATCHING.value, OrderStatus.COMMITTED_WAIT_MARKET_OPEN.value}
        committed_orders = [o for o in orders if o.get("status") in committed_statuses]
        for o in committed_orders:
            order_id = o.get("id") or o.get("order_id") or o.get("ordno")
            try:
                refreshed = self.middleware.sync_state(order_id)
                if refreshed:
                    update_at = self.get_market_time()["mock_current_time"]
                    update_order_status_to_db(conn=self.db, oid=order_id, status=refreshed.status.value, updated_at=update_at)
                    res.append(refreshed)
            except Exception as e:
                print(f"Error refreshing order {order_id}: {e}")
        return res


    def list_orders(self) -> List[Trade]:
        """Return the account's orders.

        Returns
        -------
        List[Trade]

        Warnings
        --------
        Makes a network call to the ArenaX server.
        """
        # GET /api/v1/orders, not the whole account: this skips rebuilding and
        # re-pricing every position just to read the order list.
        return [Trade(**o) for o in self.middleware.list_orders()]


    def is_market_open(self) -> bool:
        """Return whether the server's market time is on a weekday, 09:00-13:30.

        Returns
        -------
        bool

        Warnings
        --------
        Makes a network call. Holidays are not considered.
        """
        return self.middleware.is_market_open()


    def get_broker_name(self) -> str:
        """Return ``'arenax (<port>)'``."""
        return f"arenax ({self.port})"


    def get_system_time(self) -> dict:
        """Deprecated alias for get_market_time()."""
        return self.get_market_time()


    # 所有 datetime 在 JSON 邊界都用 .isoformat() 序列化
    # 接收方用 fromisoformat() 反序列化 任何地方不做 timezone 轉換!!
    # 所有 datetime 都是 隱性台北時間的 naive datetime
    def get_market_time(self) -> dict:
        """Return the server clock, with datetimes parsed from ISO 8601.

        See BrokerAPIBase.get_market_time for the keys.

        Returns
        -------
        dict

        Warnings
        --------
        Makes a network call; the result depends on the server clock.
        """
        # Server emits all datetime fields as ISO 8601 (naive Asia/Taipei).
        # Parse with fromisoformat(); no timezone conversion needed.
        #
        # playback_speed and paused are forwarded, not dropped: the server
        # already reports both, and a caller that wants to scale its own
        # waiting needs the speed. Dropping them here is what forced callers to
        # reach through to
        # middleware.get_config()['internal_config']['playback_speed'] instead.
        t = self.middleware.get_market_time()
        return {
            "mock_current_time": datetime.fromisoformat(t['mock_current_time']),
            "real_current_time": datetime.fromisoformat(t['real_current_time']),
            "mock_init_time":    datetime.fromisoformat(t['mock_init_time']),
            "real_init_time":    datetime.fromisoformat(t['real_init_time']),
            "playback_speed":    float(t.get('playback_speed', 1.0)),
            "paused":            bool(t.get('paused', False)),
        }


    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
        """Place a limit buy order for a stock.

        Builds a TSE stock order with LMT price type and ROD order type and passes
        it to place_order().

        Parameters
        ----------
        symbol : str
            Stock symbol, e.g. ``'2330'``.
        quantity : int
            Order quantity.
        price : float
            Limit price.
        intraday_odd : bool, optional
            True for an intraday odd-lot order, False for a board-lot order.
        opt_field : dict, optional
            Extra fields attached to the order.

        Returns
        -------
        OrderResult

        Warnings
        --------
        Makes a network call (simulated order, not a real one) and writes the
        order to the local mirror database.
        """
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
        """Place a limit sell order for a stock.

        Builds a TSE stock order with LMT price type and ROD order type and passes
        it to place_order().

        Parameters
        ----------
        symbol : str
            Stock symbol, e.g. ``'2330'``.
        quantity : int
            Order quantity.
        price : float
            Limit price.
        intraday_odd : bool, optional
            True for an intraday odd-lot order, False for a board-lot order.
        opt_field : dict, optional
            Extra fields attached to the order.

        Returns
        -------
        OrderResult

        Warnings
        --------
        Makes a network call (simulated order, not a real one) and writes the
        order to the local mirror database.
        """
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
