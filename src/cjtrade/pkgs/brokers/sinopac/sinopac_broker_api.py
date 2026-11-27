import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List

import shioaji as sj
from cjtrade.pkgs import paths
from cjtrade.pkgs.brokers.base_broker_api import *
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_bidask
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_kbar
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_result
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_snapshot
from cjtrade.pkgs.brokers.sinopac._internal_func import _retrieve_sinopac_trade_by_cj_order_id
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_order
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_product
from cjtrade.pkgs.brokers.sinopac._internal_func import _to_sinopac_ranktype
from cjtrade.pkgs.brokers.sinopac._internal_func import cj_sj_order_map
from cjtrade.pkgs.config.broker_settings import sinopac_credentials
from cjtrade.pkgs.db.db_api import *
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.models.event import *
from cjtrade.pkgs.models.kbar import Kbar  # explicit, so get_kbars' annotation is traceable
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.rank_type import *
from cjtrade.pkgs.models.trade import *

log = get_logger("brokers.sinopac")

class SinopacBrokerAPI(BrokerAPIBase):
    """Broker API for Sinopac, built on shioaji.

    Parameters
    ----------
    **config
        Required: ``api_key``, ``secret_key``, ``ca_path``, ``ca_passwd``.
        Optional: ``simulation`` (default True), ``username`` (default
        ``'user999'``), ``mirror_db_path``.

    Raises
    ------
    ValueError
        A required config key is missing.

    Warnings
    --------
    With ``simulation=False`` every order method acts on a REAL account.
    """
    def __init__(self, **config: Any):
        super().__init__(**config)

        # Check required config parameters
        required_params = ['api_key', 'secret_key', 'ca_path', 'ca_passwd']
        for param in required_params:
            if param not in config:
                raise ValueError(f"SinopacBrokerAPI needs: {param}")

        self.api_key = config['api_key']
        self.secret_key = config['secret_key']
        self.ca_path = config['ca_path']
        self.ca_password = config['ca_passwd']
        self.simulation = config.get('simulation', True)
        self._connected = False
        # Baseline for get_market_time()'s *_init_time. A live broker has no
        # "start of a simulated timeline", so the session start is the closest
        # honest answer.
        self._session_start = datetime.now()

        self._cached_closed_prices: dict = {}

        # db connection
        self.username = config.get('username', 'user999')
        self.db_path = config.get('mirror_db_path') or str(paths.mirror_db_path('sinopac'))
        self.db = None

        self.api = sj.Shioaji(simulation=self.simulation)

        # TODO: Trade history for accurate tax calculation
        # self.trade_history_path = config.get('trade_history_path', '.sinopac_trade_history.json')
        # self.trade_history = {}  # {symbol: [{"shares": 1000, "price": 100, "date": "2026-01-01", "side": "buy"}]}

        # Callbacks
        self._shioaji_callback_registered = False
        self._order_callbacks = []
        self._order_status_cache = {}  # {order_id: OrderStatus}


    def connect(self) -> bool:
        """Log in, activate the CA certificate and open the local mirror database.

        Returns True at once if already connected.

        Returns
        -------
        bool
            True on success; errors are logged and give False.

        Warnings
        --------
        Makes network calls and opens (creating if needed) the mirror database file.
        """
        if self._connected:  # Avoid reconnecting
            return True
        try:
            # self._load_trade_history()

            self.api.login(
                api_key=self.api_key,
                secret_key=self.secret_key,
            )
            self.api.activate_ca(
                ca_path=self.ca_path,
                ca_passwd=self.ca_password,
            )
            self._connected = True

            self.db = connect_sqlite(database=self.db_path)
            prepare_cjtrade_tables(conn=self.db)

            # self._sync_positions_with_broker()
            return True
        except Exception as e:
            log.error("conn failed: %s", e)
            self._connected = False
            return False


    def disconnect(self) -> None:
        """Log out of shioaji and close the mirror database.

        Errors from either step are logged, not raised.

        Warnings
        --------
        Makes a network call to Sinopac.
        """
        if self._connected:
            try:
                # NOTE: shioaji's C++ layer may raise pybind11::error_already_set
                # during logout when its internal event thread tries to call a
                # dict-like contract object as a function.  Swallow at Python
                # level; the C++ terminate() is unavoidable from user-side code
                # but at least we can keep the Python stack clean.
                self.api.logout()
                log.info("disconnected")
            except Exception as e:
                log.warning("shioaji logout err (known pybind11 issue): %s", e)
            try:
                self.db.close()
                log.info("local mirror DB closed")
            except Exception as e:
                log.error("close local DB failed: %s", e)
            finally:
                self._connected = False


    def is_connected(self) -> bool:
        """Return whether the broker session is open.

        Returns
        -------
        bool
        """
        return self._connected


    def market_data(self):
        """Return a SinopacMarketData that shares this session.

        Returns
        -------
        SinopacMarketData
        """
        from cjtrade.pkgs.marketdata.sinopac import SinopacMarketData
        return SinopacMarketData(self)

    def get_positions(self) -> List[Position]:
        """Return current stock positions, quantities in shares.

        Returns
        -------
        List[Position]
            Empty if the API call fails (the error is printed).

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes a network call. An API failure looks the same as an empty account.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Get position (inventory) via shioaji api (in shares)
            positions = self.api.list_positions(unit=sj.constant.Unit.Share)
            result = []

            for pos in positions:
                # Convert to standard Position format
                position = Position(
                    symbol=pos.code,
                    quantity=pos.quantity,
                    avg_cost=pos.price,
                    current_price=pos.last_price,
                    market_value=pos.quantity * pos.last_price,
                    unrealized_pnl=pos.pnl
                )
                result.append(position)

            return result
        except Exception as e:
            log.error("get positions failed: %s", e)
            return []


    def get_balance(self) -> float:
        """Get account balance.

        Returns
        -------
        float

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes a network call to Sinopac.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        account_status = self.api.account_balance()
        return account_status.acc_balance


    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        """Return the latest bid/ask quote for a product.

        Subscribes to bid/ask quotes, waits up to 5 seconds for one, then
        unsubscribes.

        Parameters
        ----------
        product : Product
        intraday_odd : bool, optional
            Subscribe to the intraday odd-lot book.

        Returns
        -------
        BidAsk or None
            None if no quote arrived within 5 seconds.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes network calls, blocks for up to 5 seconds, and replaces the
        shioaji bid/ask quote callback.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        sinopac_product = _to_sinopac_product(self.api, product)
        received_bidask = []

        def quote_callback(exchange, bidask):
            received_bidask.append(bidask)

        self.api.quote.set_on_bidask_stk_v1_callback(quote_callback)

        subscribe_kwargs = {
            "quote_type": sj.constant.QuoteType.BidAsk,
            "version": sj.constant.QuoteVersion.v1
        }
        if intraday_odd:
            subscribe_kwargs["intraday_odd"] = True

        self.api.quote.subscribe(sinopac_product, **subscribe_kwargs)

        import time
        timeout = 5
        start = time.time()
        while not received_bidask and (time.time() - start) < timeout:
            time.sleep(0.1)

        self.api.quote.unsubscribe(sinopac_product, **subscribe_kwargs)

        if not received_bidask:
            # TODO: Consider raising exception/error here
            log.warning("no bid/ask recv for %s", product.symbol)
            return None

        return _from_sinopac_bidask(received_bidask[-1])


    # Shioaji refuses a kbars request whose start/end span more than 30 days.
    # 28 rather than 30 because the documented limit does not say whether it
    # counts the end date, and one extra request per 28 days of history is not
    # a cost worth the ambiguity.
    _KBAR_MAX_DAYS = 28

    # start: str in "YYYY-MM-DD" format
    # end: str in "YYYY-MM-DD" format (exclusive - will not include this date)
    # interval: str (e.g. 1m/3m/5m/15m/30m/1h/1d)
    def get_kbars(self, product: Product, start: str, end: str, interval: str = "1m"):
        """Kbars for any date range, in windows Shioaji will accept.

        The 30-day cap is a property of the Sinopac API, so the splitting
        belongs here rather than in each caller. It was previously done by
        ArenaX_BackendBase.kbars (30-day chunks) and by
        market_data._fetch_from_real_account (28-day chunks) and by nobody
        else -- so the same rule was written twice with two different numbers,
        while real_backend.kbars and every direct client caller passed the
        range straight through. `cjshell`'s kbars command takes the range
        from the user, and the example in pkgs/analytics/technical asks for a
        whole year.

        Those two callers now hand this an already-short range and the loop
        below runs once, so they are redundant rather than wrong.

        Parameters
        ----------
        product : Product
        start : str
            Start date, ``YYYY-MM-DD``.
        end : str
            End date, ``YYYY-MM-DD``, exclusive.
        interval : str, optional
            e.g. '1m', '5m', '1h', '1d'. Bars other than '1m' are aggregated
            from 1-minute bars.

        Returns
        -------
        List[Kbar]
            Empty if end is not after start.

        Raises
        ------
        ConnectionError
            Not connected.
        ValueError
            The interval is not supported.

        Warnings
        --------
        Makes one network call per 28-day window; any window failure is re-raised.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        from datetime import datetime, timedelta

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        if end_dt <= start_dt:
            return []

        sinopac_product = _to_sinopac_product(self.api, product)
        base_kbars: List[Kbar] = []
        window_start = start_dt

        while window_start < end_dt:
            window_end = min(window_start + timedelta(days=self._KBAR_MAX_DAYS),
                             end_dt)
            # `end` is exclusive in this method's contract and inclusive in
            # Shioaji's, so every window converts the same way the whole range
            # used to. Windows are half-open and advance by their own end, so
            # no bar is fetched twice and none is skipped.
            try:
                kbars_1m = self.api.kbars(
                    contract=sinopac_product,
                    start=window_start.strftime("%Y-%m-%d"),
                    end=(window_end - timedelta(days=1)).strftime("%Y-%m-%d"),
                )
                base_kbars.extend(_from_sinopac_kbar(kbars_1m, product.symbol))
            except Exception as e:
                # Still raised rather than returning what arrived so far.
                # Callers depend on it: ArenaX_BackendBase.kbars falls through
                # to yfinance on an exception, and it records cache coverage
                # for whatever it was handed -- a silent partial result would
                # be written to the price cache and marked complete.
                log.error("kbars %s [%s, %s) failed: %s", product.symbol,
                          window_start.date(), window_end.date(), e)
                raise

            window_start = window_end

        base_kbars.sort(key=lambda k: k.timestamp)

        # If requesting 1m data, return as-is
        if interval == "1m":
            return base_kbars

        # Aggregated once over the whole range, never per window: a bar longer
        # than a window -- 1w, 1M -- would otherwise be cut at the boundary and
        # emitted as two partial bars.
        try:
            from ._internal_func import _aggregate_kbars
            return _aggregate_kbars(base_kbars, interval)
        except ValueError as e:
            raise ValueError(f"Interval '{interval}' not supported: {e}") from e


    # Return close prices for given products at any time
    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """Return snapshots for the given products.

        While the market is closed, results are cached per tuple of symbols;
        the cache is cleared when the market is open.

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
        Makes a network call. Caching depends on the local wall clock.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        def fetch():
            sinopac_products = [_to_sinopac_product(self.api, p) for p in products]
            sinopac_snapshots = self.api.snapshots(sinopac_products)
            cj_snapshots = []
            for snapshot in sinopac_snapshots:
                cj_snapshot = _from_sinopac_snapshot(snapshot)
                cj_snapshots.append(cj_snapshot)
            return cj_snapshots

        # Market open → always fetch (and invalidate stale close cache)
        if self.is_market_open():
            self._cached_closed_prices = {}
            return fetch()

        # Market closed → per-symbol cache
        cache_key = tuple(p.symbol for p in products)
        if cache_key not in self._cached_closed_prices:
            self._cached_closed_prices[cache_key] = fetch()
        return self._cached_closed_prices[cache_key]


    # TODO: Finish this
    # def register_price_callback(self, cb_type: PriceCallbackType, callback, **kwargs):
    #     pass
        # If PriceCbType == TIME_PERIOD
        # if cb_type == PriceCallbackType.TIME_PERIOD:
        #     pass
        # elif cb_type == PriceCallbackType.PRICE_CHANGE:
        #     pass
        # else:
        #     raise ValueError(f"Unsupported PriceCallbackType: {cb_type}")


    def register_order_callback(self, callback: OrderCallback) -> None:
        """Register callback for order status changes (including fills).

        Callback receives unified OrderEvent from CJ abstraction layer.

        Warnings
        --------
        The first call installs a shioaji order callback. Logs at DEBUG.
        """
        self._order_callbacks.append(callback)
        log.debug("order cb registered, n=%d", len(self._order_callbacks))

        if not self._shioaji_callback_registered:
            log.debug("setting up shioaji order cb (first time)")
            self._setup_shioaji_order_callback()
            self._shioaji_callback_registered = True
        else:
            log.debug("shioaji cb already registered, skip setup")


    # Sinopac-specific method
    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:
        """Return the top movers from the Sinopac scanner, keyed by product name.

        Parameters
        ----------
        top_n : int, optional
            Number of products to return.
        by : RankType, optional
            Ranking criterion.
        ascending : bool, optional
            Sort order.

        Returns
        -------
        Dict[str, Snapshot]

        Raises
        ------
        ConnectionError
            Not connected.
        ValueError
            The scanner or snapshot call failed.

        Warnings
        --------
        Makes a network call to Sinopac.
        """

        if not self._connected:
            raise ConnectionError("Not connected to broker")
        try:
            sj_rank_type = _to_sinopac_ranktype(by)
            movers = self.api.scanners(
                scanner_type=sj_rank_type,
                ascending=ascending,
                count=top_n
            )  # Returns a List[shioaji.data.ChangePercentRank]
            codes = [mover.code for mover in movers]
            names = [mover.name for mover in movers]
            cj_snapshots = self.get_snapshots([Product(symbol=code) for code in codes])
            result = {}
            for i, cj_snapshot in enumerate(cj_snapshots):
                cj_snapshot.name = names[i]  # Add name info
                result[cj_snapshot.name] = cj_snapshot
            return result
        except Exception as e:
            raise ValueError(f"Cannot get market movers from Sinopac: {e}") from e


    # TODO: Remove comments when it is stable
    def place_order(self, order: Order) -> OrderResult:
        """Place an order on Sinopac.

        1. Convert CJ Order -> Sinopac order + Sinopac contract (product)
        2. Store the mapping between CJ ID and Sinopac order obj through cj_sj_order_map (in-memory dict) and DB (permanent storage)
        3. Place order via Sinopac API

        Parameters
        ----------
        order : Order

        Returns
        -------
        OrderResult
            REJECTED with the error message if any step fails.

        Raises
        ------
        ConnectionError
            Not connected.
        NotImplementedError
            The order type is GTC.

        Warnings
        --------
        Places a REAL order on a real account unless ``simulation`` is True.
        Also writes to the local mirror database.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        if order.order_type == OrderType.GTC:
            raise NotImplementedError("GTC orders are not yet supported in Sinopac")

        try:
            sinopac_product = _to_sinopac_product(self.api, order.product)
            sinopac_order = _to_sinopac_order(self.api, order)
            sinopac_trade = self.api.place_order(sinopac_product, sinopac_order)

            # Store mapping using shioaji order id, not cj order id
            sj_order_id = sinopac_trade.order.id
            cj_sj_order_map[order.id] = sinopac_trade
            insert_new_ordermap_item_to_db(conn=self.db, cj_order_id=order.id, bkr_order_id=sj_order_id, broker='sinopac')  # Store mapping in DB

            order_result = _from_sinopac_result(sinopac_trade)
            order_result.linked_order = order.id

            # Maintain local records
            insert_new_order_to_db(conn=self.db, username=self.username, order=order)
            return order_result

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Order failed: {e}",
                metadata={},
                linked_order=""
            )

    # Replaces the old commit_order(): sinopac has no staging area, so place_order()
    # submits immediately.  This method just calls sj.update_status() to refresh the
    # local order map – hence the more accurate name sync_state().
    def sync_state(self) -> List[OrderResult]:
        """Refresh order status from Sinopac and return the orders still open.

        Only orders in the in-memory order map are checked; filled, cancelled
        and failed ones are left out.

        Returns
        -------
        List[OrderResult]
            On error, a single REJECTED OrderResult instead of a list.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes a network call, writes order status to the mirror database and
        logs the order map at DEBUG.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")
        try:
            # Update status to refresh all trade information
            self.api.update_status(self.api.stock_account)

            res = []
            log.debug("order map: %s", cj_sj_order_map)
            # TODO: Not only check in-mem but also check in DB
            from ._internal_func import STATUS_MAP

            for c, s in cj_sj_order_map.items():
                if s.status.status not in [sj.constant.Status.Cancelled,
                                           sj.constant.Status.Failed,
                                           sj.constant.Status.Filled]:
                    # Map actual Shioaji status to CJ status
                    cj_status = STATUS_MAP.get(s.status.status, OrderStatus.UNKNOWN)
                    res.append(_from_sinopac_result(s))
                    update_order_status_to_db(conn=self.db, oid=c, status=cj_status.value)

            return res

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to commit order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order='N/A'
            )


    # TODO: Currently CJ ID is not permanently stored, so sometimes we cannot find the order to cancel.
    # We need to find a better way to store the mapping (e.g. store in DB permanently instead of in-memory dict)
    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order.

        Parameters
        ----------
        order_id : str
            The CJTrade order id.

        Returns
        -------
        OrderResult
            REJECTED with the reason if the order is not found, already final,
            or the cancel fails.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Cancels a REAL order on a real account unless ``simulation`` is True.
        Also writes to the local mirror database.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status(self.api.stock_account)
            trade_obj = _retrieve_sinopac_trade_by_cj_order_id(api=self.api, db_conn=self.db, cj_order_id=order_id)

            if trade_obj is None:
                raise Exception(f"Order with ID {order_id} not found")

            if trade_obj.status.status in [sj.constant.Status.Filled, sj.constant.Status.Cancelled, sj.constant.Status.Failed]:
                raise Exception(f"Cannot be cancelled because it is already {trade_obj.status.status}")

            self.api.cancel_order(trade_obj)
            self.api.update_status(self.api.stock_account)
            update_order_status_to_db(conn=self.db, oid=order_id, status='CANCELLED')

            return _from_sinopac_result(trade_obj)

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to cancel order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order=order_id
            )


    # NOTE: Decouple from sj API/objects, use cj internal obj (`Trade`) instead
    # This is quite important since other equivalent feature have been
    # abstracted in cjtrade-based dataclass. (Don't simply use List[Dict])
    def list_orders(self) -> List[Trade]:
        """Return the account's orders as Trade objects.

        Returns
        -------
        List[Trade]
            Empty if the API call fails (the error is printed).

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Makes a network call to Sinopac.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status()  # Refresh status
            trades = self.api.list_trades()

            orders = []

            for trade in trades:
                # Convert Sinopac status to CJ status
                from ._internal_func import STATUS_MAP
                cj_status = STATUS_MAP.get(trade.status.status, OrderStatus.UNKNOWN)

                order_info = Trade(
                    # id=trade.status.id,
                    # id=cj_order_id,
                    id=get_cj_order_id_from_db(conn=self.db, bkr_order_id=trade.status.id) or 'N/A',
                    symbol=getattr(trade.contract, 'code', 'N/A') if hasattr(trade, 'contract') else 'N/A',
                    action=trade.order.action.value if hasattr(trade.order, 'action') else 'N/A',
                    quantity=trade.order.quantity,
                    price=trade.order.price,
                    status=cj_status.value,  # Use converted CJ status
                    order_type=trade.order.order_type.value if hasattr(trade.order, 'order_type') else 'N/A',
                    price_type=trade.order.price_type.value if hasattr(trade.order, 'price_type') else 'N/A',
                    order_lot=trade.order.order_lot.value if hasattr(trade.order, 'order_lot') else 'N/A',
                    order_datetime=trade.status.order_datetime.strftime('%Y-%m-%d %H:%M:%S') if hasattr(trade.status, 'order_datetime') else 'N/A',
                    deals=len(trade.status.deals) if hasattr(trade.status, 'deals') else 0,
                    ordno=trade.order.ordno if hasattr(trade.order, 'ordno') else 'N/A'
                )

                orders.append(order_info)

            return orders

        except Exception as e:
            # TODO: Consider raising exception/error here
            log.error("list_orders failed: %s", e)
            return []


    def is_market_open(self) -> bool:
        """Return whether the local time is on a weekday, 09:00-13:30.

        Returns
        -------
        bool

        Warnings
        --------
        Uses the local wall clock. Holidays are not considered.
        """
        # Check within 9AM - 13:30PM on weekdays (Mon-Fri)
        now = datetime.now()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close_time = now.replace(hour=13, minute=30, second=0, microsecond=0)
        return market_open_time <= now <= market_close_time

    def get_market_time(self) -> dict:
        """Live broker: market time IS real time, at 1x, never paused.

        The mock_* keys mirror the real ones rather than saying "not a mock
        broker": callers that ask what time the market is at should get a
        datetime from every broker, so they can stay broker-agnostic instead of
        branching on the broker name. Reporting the live case as the 1x,
        never-paused instance of the same contract is what lets a caller scale
        its own sleeps uniformly.

        Warnings
        --------
        Uses the local wall clock.
        """
        now = datetime.now()
        return {
            "mock_current_time": now,
            "real_current_time": now,
            "mock_init_time": self._session_start,
            "real_init_time": self._session_start,
            "playback_speed": 1.0,
            "paused": False,
        }


    def get_broker_name(self) -> str:
        """Return ``'sinopac'``."""
        return "sinopac"


    ##### SIMPLE HIGH-LEVEL METHODS (START) #####
    # Simple API with default config
    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True, opt_field: dict = None) -> OrderResult:
        """Place a limit buy order for a stock.

        Builds a TSE stock order with LMT price type and ROD order type, places
        it, then calls sync_state() to update the returned status.

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
            Accepted but not used.

        Returns
        -------
        OrderResult

        Warnings
        --------
        Places a REAL order on a real account unless ``simulation`` is True.
        Also writes to the local mirror database.
        """
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,  # Assuming TSE for simplicity
            symbol=symbol
        )
        log.debug("intraday_odd=%s", intraday_odd)

        order = Order(
            product=product,
            action=OrderAction.BUY,
            price=price,
            quantity=quantity,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common
        )

        temp = self.place_order(order)
        state = next(
            (s for s in self.sync_state() if s.linked_order == order.id),
            None
        )

        if state is not None:
            temp.status = state.status
        else:
            log.warning("sync state for order %s failed, using local result", order.id)

        return temp


    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True, opt_field: dict = None) -> OrderResult:
        """Place a limit sell order for a stock.

        Builds a TSE stock order with LMT price type and ROD order type, places
        it, then calls sync_state() to update the returned status.

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
            Accepted but not used.

        Returns
        -------
        OrderResult

        Warnings
        --------
        Places a REAL order on a real account unless ``simulation`` is True.
        Also writes to the local mirror database.
        """
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )

        order = Order(
            product=product,
            action=OrderAction.SELL,
            price=price,
            quantity=quantity,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common
        )
        temp = self.place_order(order)
        state = next(
            (s for s in self.sync_state() if s.linked_order == order.id),
            None
        )

        if state is not None:
            temp.status = state.status
        else:
            log.warning("sync state for order %s failed, using local result", order.id)

        return temp
    ##### SIMPLE HIGH-LEVEL METHODS (END) #####

    ##### INTERNAL METHODS (START) #####
    # TODO: Review callback registration logic
    def _setup_shioaji_order_callback(self):

        def shioaji_order_status_callback(stat, msg):
            """Shioaji native callback
            Args:
                stat: shioaji.order.OrderState
                    - status: Status enum (PendingSubmit, Submitted, Filled, etc.)
                    - id
                    - order_datetime
                    - deals: list of deal details
                    - deal_price
                    - deal_quantity
                msg: message string
            """
            log.debug("shioaji cb: stat=%s, msg keys=%s", stat, msg.keys() if msg else None)

            try:
                from ._internal_func import OPERATION_TYPE_MAP, STATUS_MAP

                # 1. Check callback type: OrderState vs Deal
                if stat.name == 'StockDeal':
                    # Deal callback: different structure
                    # Use seqno to look up the order (ordno might not match DB)
                    log.debug("deal cb")
                    op_type = 'Deal'
                    sj_seqno = msg['seqno']
                    cj_status = STATUS_MAP.get(stat, OrderStatus.FILLED)
                    log.debug("deal seqno=%s, cj_status=%s", sj_seqno, cj_status)

                    # Find order_id from seqno by checking the in-memory map first
                    matching_trade = None
                    sj_order_id = None

                    # Check in-memory map first (fastest)
                    for cj_id, trade in cj_sj_order_map.items():
                        if hasattr(trade, 'order') and hasattr(trade.order, 'seqno'):
                            if trade.order.seqno == sj_seqno:
                                matching_trade = trade
                                sj_order_id = trade.order.id
                                break

                    # Fallback: query API (slower)
                    if not matching_trade:
                        trades = self.api.list_trades()
                        # list_trades() returns a list, not dict
                        for trade in trades:
                            if hasattr(trade, 'order') and hasattr(trade.order, 'seqno'):
                                if trade.order.seqno == sj_seqno:
                                    matching_trade = trade
                                    sj_order_id = trade.order.id
                                    break

                    if not matching_trade:
                        log.warning("no order with seqno=%s, ignored", sj_seqno)
                        return

                    log.debug("matched order %s", sj_order_id)
                else:
                    # Order status callback: has 'operation' field
                    log.debug("order status cb")
                    op_type = msg['operation']['op_type']
                    sj_order_id = msg['order']['id']
                    cj_status = OPERATION_TYPE_MAP.get(op_type, OrderStatus.UNKNOWN)
                    log.debug("sj_order_id=%s, op_type=%s, cj_status=%s", sj_order_id, op_type, cj_status)

                # 2. Get CJ order_id from DB
                cj_order_id = get_cj_order_id_from_db(conn=self.db, bkr_order_id=sj_order_id)
                log.debug("cj_order_id for sj_order_id=%s: %s", sj_order_id, cj_order_id)
                if not cj_order_id:
                    log.warning("cj order_id for sj_order_id=%s not in DB, cb ignored", sj_order_id)
                    return  # Ignore if not found

                # 3. Get the complete trade object (including contract information)
                trade_obj = _retrieve_sinopac_trade_by_cj_order_id(api=self.api, db_conn=self.db, cj_order_id=cj_order_id)
                if not trade_obj:
                    log.warning("trade obj not found for cj_order_id=%s", cj_order_id)
                    return  # Ignore if not found

                # 4. Extract order information from msg dict
                if stat.name == 'StockDeal':
                    # Deal structure
                    symbol = msg['code']
                    action_str = msg['action']
                    quantity = msg['quantity']
                    price = msg['price']
                else:
                    # Order status structure
                    symbol = msg['contract']['code']
                    action_str = msg['order']['action']
                    quantity = msg['order']['quantity']
                    price = msg['order']['price']

                # Convert action string to CJ OrderAction
                from cjtrade.pkgs.models.order import OrderAction
                if action_str == 'Buy':
                    cj_action = OrderAction.BUY
                elif action_str == 'Sell':
                    cj_action = OrderAction.SELL
                else:
                    cj_action = None

                # 5. Get old status (for detecting changes)
                old_status = self._order_status_cache.get(cj_order_id, OrderStatus.PLACED)

                # 6. Extract filled quantity and price
                if stat.name == 'StockDeal':
                    # Deal: quantity and price are the filled amounts
                    filled_qty = quantity
                    filled_price = price
                else:
                    # Order status: look in status field
                    filled_qty = msg.get('status', {}).get('deal_quantity', 0)
                    filled_price = msg.get('status', {}).get('deal_price', None)

                # Calculate filled_value
                filled_value = filled_qty * filled_price if filled_price else None

                # 7. Create OrderEvent (unified CJ abstraction layer format)
                order_event = OrderEvent(
                    event_type=EventType.ORDER_STATUS_CHANGE,
                    timestamp=datetime.now(),
                    order_id=cj_order_id,
                    symbol=symbol,
                    action=cj_action,
                    quantity=quantity,
                    price=price,
                    old_status=old_status,
                    new_status=cj_status,
                    filled_quantity=filled_qty,
                    filled_price=filled_price,
                    filled_value=filled_value,
                    message=str(msg),
                    broker_raw_data={
                        'sj_order_id': sj_order_id,
                        'sj_status': str(stat),
                        'sj_msg': msg,
                        'op_type': op_type,
                        'deal_id': msg.get('trade_id', sj_order_id) if stat.name == 'StockDeal' else sj_order_id
                    }
                )

                # 8. Update status cache
                self._order_status_cache[cj_order_id] = cj_status

                # 9. Trigger order callbacks
                log.debug("triggering %d order cbs", len(self._order_callbacks))
                for callback in self._order_callbacks:
                    try:
                        callback(order_event)
                    except Exception as e:
                        log.exception("order cb failed: %s", e)

                # 9. Update database status
                update_order_status_to_db(conn=self.db, oid=cj_order_id, status=cj_status.value)

            except Exception as e:
                log.exception("shioaji cb handler failed: %s", e)

        # Callback function registration
        result = self.api.set_order_callback(shioaji_order_status_callback)
        log.info("shioaji order cb registered (ret=%s)", result)

    ##### INTERNAL METHODS (END) #####



# Test cb registration by CJTrade API
## TODO: When market open, test the same scenarios as the test plan for Sinopac native API
##   - [x] Run this, and use ./test/test_sinopac_api_update_qty.py to reduce quantity by 1 to verify if cb is triggered (UPDATE),
##   - [x] and use "v0.1.0" cjtrade shell to cancel all order to verify if cb is triggered (CANCEL).
##   - [x] and use sinopac android app to manually reduce the order quantity by 2 to verify if cb is triggered (UPDATE),
##   - [x] Run this again to create another order, and use sinopac android app to manually cancel the order to verify if cb is triggered (CANCEL)
##   - [x] Run this again (change buy price higher) let it be filled, and verify if cb is triggered (FILL).
if __name__ == "__main__":
    from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType
    from cjtrade.pkgs.models.order import Order, OrderAction, PriceType, OrderType
    from cjtrade.pkgs.models.product import Product, Exchange
    from cjtrade.pkgs.config.config_loader import load_supported_config_files
    import time
    from cjtrade.pkgs.logger import get_console
    from cjtrade.pkgs.logger import setup_logging

    setup_logging()
    out = get_console()
    load_supported_config_files()

    client = AccountClient(
        BrokerType.SINOPAC,
        **sinopac_credentials(),
        simulation=False
    )
    client.connect()

    # 2. Define callback for order status changes (including fills)
    def on_order_change(event: OrderEvent):
        out.info(f"\n📝 Order Status Change")
        out.info(f"  Order ID: {event.order_id}")
        out.info(f"  Symbol: {event.symbol}")
        out.info(f"  {event.old_status.value} → {event.new_status.value}")

        # Check if order is filled
        if event.is_filled():
            out.info(f"\n🎉 Order Filled!")
            out.info(f"  Action: {event.action.value}")
            out.info(f"  Filled Quantity: {event.filled_quantity}")
            out.info(f"  Filled Price: {event.filled_price}")
            out.info(f"  Filled Value: {event.filled_quantity * event.filled_price if event.filled_price else 0}")

            if event.is_completely_filled():
                out.info(f"  ✅ Order Completely Filled")
            else:
                out.info(f"  ⏳ Partial Fill")

        # Check other status
        if event.is_rejected():
            out.info(f"  ❌ Rejection Reason: {event.message}")
        elif event.is_cancelled():
            out.info(f"  ⚠️ Order Cancelled")

    # 3. Register callback
    client.register_order_callback(on_order_change)

    # 4. Place order test
    order = Order(
        product=Product(
            symbol="2890",
            # symbol="0050",
            exchange=Exchange.TSE
        ),
        action=OrderAction.BUY,
        # price=28.5,  # close price on 2026-02-26
        price=31.65,  # close price on 2026-02-26
        # price=77.15,  # close price on 2026-02-26
        # quantity=10,
        quantity=2,
        order_lot=OrderLot.IntraDayOdd,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD
    )

    out.info(f"\n📮 Placing Order: Buy {order.product.symbol} x{order.quantity} @ {order.price}")
    result = client.place_order(order)
    out.info(f"  Order Result: {result.status.value}")

    if result.status == OrderStatus.PLACED:
        out.info(f"\n📤 Submitting Order")
        commit_results = client.sync_state()
        for res in commit_results:
            out.info(f"  Submission Result: {res.status.value}")

    # 5. Keep the program running, waiting for callback triggers
    out.info(f"\n⏳ Waiting for order fills (Ctrl+C to exit)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        out.info(f"\n👋 Connection closed")
        client.disconnect()
