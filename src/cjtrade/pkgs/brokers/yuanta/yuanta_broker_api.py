"""Broker API for Yuanta Securities (元大證券), on Yuanta's Spark API.

Usage::

    from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

    client = AccountClient(BrokerType.YUANTA, account="S98875005091", password="...",
                           cert_path="/path/to/cert.pfx", cert_pass="...",
                           dll_dir="/path/to/YuantaSparkAPI", environment="UAT")
    client.connect()

The Spark API is asynchronous: every call returns at once, and its result
arrives later through the ``OnResponse`` event, named by the function
(``strIndex``). This adapter sends a call, waits for that named response and
returns it, so its methods are blocking like every other broker's.

Warnings
--------
Testing in progress: not yet run against a Yuanta account. With
``environment="PROD"`` every order is real.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs import paths
from cjtrade.pkgs.brokers.base_broker_api import BrokerAPIBase
from cjtrade.pkgs.brokers.yuanta import _internal_func as yx
from cjtrade.pkgs.brokers.yuanta import _spark
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import get_cj_order_id_from_db
from cjtrade.pkgs.db.db_api import insert_new_order_to_db
from cjtrade.pkgs.db.db_api import insert_new_ordermap_item_to_db
from cjtrade.pkgs.db.db_api import prepare_cjtrade_tables
from cjtrade.pkgs.db.db_api import update_order_status_to_db
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.models.event import EventType
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.trade import Trade

log = get_logger("brokers.yuanta")

OrderCallback = Callable[[OrderEvent], None]

# intMark of OnResponse.
MARK_SYSTEM, MARK_QUERY, MARK_SUBSCRIPTION = 0, 1, 2
# dwIndex of a system message (intMark 0).
SYS_CONNECTED, SYS_DISCONNECTED, SYS_NETWORK_ERROR = 1, 2, 3
# Yuanta allows 3 account queries a second per function; stay under it.
MIN_QUERY_INTERVAL = 0.35


class _Waiter:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: Optional[str] = None


class YuantaBrokerAPI(BrokerAPIBase):
    """Broker API for Yuanta, on the Spark API.

    Parameters
    ----------
    **config
        Required: ``account`` (``S`` + branch (4) + account (7), e.g.
        ``S98875005091``), ``password``, ``dll_dir`` (the folder holding
        ``YuantaSparkAPI.dll``). ``cert_path`` and ``cert_pass`` are required
        on Linux and macOS. Optional: ``environment`` (``"UAT"``, Yuanta's test
        environment, by default; ``"PROD"`` for the real account),
        ``timeout`` (seconds to wait for a response, default 10),
        ``username``, ``mirror_db_path``.

    Raises
    ------
    ValueError
        A required config key is missing or ``environment`` is unknown.

    Warnings
    --------
    Testing in progress. With ``environment="PROD"`` every order is real.
    """

    def __init__(self, **config: Any):
        super().__init__(**config)
        missing = [k for k in ("account", "password", "dll_dir") if not config.get(k)]
        if sys.platform != "win32":
            missing += [k for k in ("cert_path", "cert_pass") if not config.get(k)]
        if missing:
            raise ValueError(f"YuantaBrokerAPI needs: {', '.join(missing)}")
        self.environment = str(config.get("environment") or "UAT").upper()
        if self.environment not in ("UAT", "PROD"):
            raise ValueError("environment must be UAT or PROD")
        self.account = config["account"]
        self.password = config["password"]
        self.cert_path = config.get("cert_path") or ""
        self.cert_pass = config.get("cert_pass") or ""
        self.dll_dir = config["dll_dir"]
        self.timeout = float(config.get("timeout") or 10)
        self.username = config.get("username", "user999")
        self.db_path = config.get("mirror_db_path") or str(paths.mirror_db_path("yuanta"))
        self.db = None
        self.spark = None
        self.trader = None
        self._connected = False
        self._session_start = datetime.now()
        self._lock = threading.RLock()
        self._waiters: Dict[str, _Waiter] = {}
        self._call_locks: Dict[str, threading.Lock] = {}
        self._last_call: Dict[str, float] = {}
        self._opened = threading.Event()
        self._identify = 0
        # CJTrade order id -> what is known about it.
        self._orders: Dict[str, dict] = {}
        self._status_cache: Dict[str, OrderStatus] = {}
        self._order_callbacks: List[OrderCallback] = []

    # ── the request / response bridge ──────────────────────────────────────

    def _on_response(self, int_mark, dw_index, str_index, obj_handle, obj_value) -> None:
        """OnResponse: route a query response to its waiter, a report to the
        report handler, and log system messages."""
        try:
            mark, index, name = int(int_mark), int(dw_index), yx.text(str_index)
            if mark == MARK_SYSTEM:
                if index == SYS_CONNECTED:
                    self._opened.set()
                elif index in (SYS_DISCONNECTED, SYS_NETWORK_ERROR):
                    log.warning("yuanta connection: %s", yx.text(obj_value))
                else:
                    log.info("yuanta: %s", yx.text(obj_value))
                return
            if mark == MARK_SUBSCRIPTION and name in ("RR_RealReport", "RR_RealReportMerge"):
                self._on_real_report(obj_value)
                return
            if mark == MARK_QUERY:
                with self._lock:
                    waiter = self._waiters.get(name) if name else None
                    if waiter is None and not name:
                        # An empty strIndex is an error for whichever call is waiting.
                        waiter = next(iter(self._waiters.values()), None)
                if waiter is None:
                    log.debug("unrequested response %s: %s", name, yx.text(obj_value)[:200])
                    return
                if not name:
                    waiter.error = yx.text(obj_value) or f"error code {index}"
                else:
                    waiter.value = obj_value
                waiter.event.set()
        except Exception as e:  # noqa: BLE001 - an exception here would be lost in .NET
            log.exception("OnResponse handler failed: %s", e)

    def _call(self, name: str, send: Callable[[], Any]) -> Any:
        """Send one call and wait for the response named `name`.

        Calls of the same function are serialised and spaced to Yuanta's limit.

        Raises
        ------
        RuntimeError
            The call was refused at once, timed out, or answered with an error.
        """
        with self._lock:
            call_lock = self._call_locks.setdefault(name, threading.Lock())
        with call_lock:
            wait = MIN_QUERY_INTERVAL - (time.monotonic() - self._last_call.get(name, 0.0))
            if wait > 0:
                time.sleep(wait)
            waiter = _Waiter()
            with self._lock:
                self._waiters[name] = waiter
            try:
                if not send():
                    raise RuntimeError(f"{name} was refused by the Spark API")
                if not waiter.event.wait(self.timeout):
                    raise RuntimeError(f"{name}: no response within {self.timeout:.0f}s")
                if waiter.error:
                    raise RuntimeError(f"{name}: {waiter.error}")
                return waiter.value
            finally:
                self._last_call[name] = time.monotonic()
                with self._lock:
                    self._waiters.pop(name, None)

    def _lang(self):
        return self.spark.enumLangType.UTF8

    # ── session ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Load the Spark API, open a connection to `environment` and log in.

        Returns
        -------
        bool
            True on success; a failure is logged with Yuanta's message and gives False.

        Warnings
        --------
        Makes network calls and opens (creating if needed) the mirror database file.
        """
        if self._connected:
            return True
        try:
            self.spark = _spark.load(self.dll_dir)
            self.trader = self.spark.Trader()
            self.trader.SetLogType(self.spark.enumLogType.COMMON)
            self.trader.OnResponse += self._on_response
            mode = getattr(self.spark.enumEnvironmentMode, self.environment)
            self.trader.Open(mode)
            if not self._opened.wait(self.timeout):
                log.warning("no Connect message within %.0fs; logging in anyway", self.timeout)
            if self.cert_path:
                send = lambda: self.trader.Login(self.cert_path, self.cert_pass,  # noqa: E731
                                                 self.account, self.password)
            else:
                send = lambda: self.trader.Login(self.account, self.password)  # noqa: E731
            result = self._call("Login", send)
        except Exception as e:  # noqa: BLE001
            log.error("login failed: %s", e)
            return False
        status = getattr(result, "LoginStatus", None)
        if not yx.msg_ok(status):
            log.error("login refused: %s %s", yx.text(getattr(status, "MsgCode", "")),
                      yx.text(getattr(status, "MsgContent", "")))
            return False
        accounts = [yx.text(getattr(a, "Account", "")) for a in (getattr(result, "LoginList", None) or [])]
        if accounts and self.account not in accounts:
            log.error("login succeeded but %s is not among its accounts %s", self.account, accounts)
            return False
        self.db = connect_sqlite(database=self.db_path)
        prepare_cjtrade_tables(conn=self.db)
        self._connected = True
        log.info("yuanta connected (%s)", self.environment)
        return True

    def disconnect(self) -> None:
        """Log out and release the connection. Errors are logged, not raised."""
        try:
            if self.trader is not None:
                if self._connected:
                    self.trader.LogOut()
                self.trader.Close()
                self.trader.Dispose()
        except Exception as e:  # noqa: BLE001
            log.error("logout failed: %s", e)
        finally:
            self._connected = False
            self._opened.clear()
            if self.db is not None:
                try:
                    self.db.close()
                except Exception as e:  # noqa: BLE001
                    log.error("closing the mirror db failed: %s", e)
                self.db = None

    def is_connected(self) -> bool:
        return self._connected

    def _require_connection(self) -> None:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

    # ── account ────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Available balance of the settlement bank account (GetBankBalance).

        Raises
        ------
        ConnectionError
            Not connected.
        RuntimeError
            The query failed.
        """
        self._require_connection()
        res = self._call("GetBankBalance", lambda: self.trader.GetBankBalance(self.account, self._lang()))
        rows = list(getattr(res, "BankBalanceList", None) or [])
        if not rows:
            raise RuntimeError("GetBankBalance returned no account")
        message = yx.text(getattr(rows[0], "Message", ""))
        if message:
            log.warning("GetBankBalance: %s", message)
        return yx.num(getattr(rows[0], "AvailableBalance", 0))

    def get_positions(self) -> List[Position]:
        """Holdings in shares, with cost, market price and unrealised P&L (GetStoreSummary)."""
        self._require_connection()
        res = self._call("GetStoreSummary", lambda: self.trader.GetStoreSummary(self.account, self._lang()))
        return yx.to_cj_positions(getattr(res, "StkStoreList", None))

    # ── quotes ─────────────────────────────────────────────────────────────

    def _quote_rows(self, symbols: List[str]) -> dict:
        """GetWatchListAll rows by symbol. Each symbol is asked as listed (TWSE)
        first, and any missing are asked again as OTC (TWOTC)."""
        rows: dict = {}
        for market in ("TWSE", "TWOTC"):
            wanted = [s for s in symbols if s not in rows]
            if not wanted:
                break
            quotes = self.spark.List[self.spark.Quote]()
            for s in wanted:
                q = self.spark.Quote()
                q.MarketType = getattr(self.spark.enumMarketType, market)
                q.StockCode = s
                quotes.Add(q)
            res = self._call("GetWatchListAll",
                             lambda: self.trader.GetWatchListAll(self.account, quotes, self._lang()))
            for row in getattr(res, "QueryWatchList", None) or []:
                code = yx.text(getattr(row, "StkCode", ""))
                if code and (yx.num(getattr(row, "DealPrice", 0)) or yx.num(getattr(row, "OpenRefPrice", 0))):
                    rows.setdefault(code, row)
        return rows

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """Latest quote per product from the quote table (GetWatchListAll).

        Raises
        ------
        ConnectionError
            Not connected.
        RuntimeError
            The query failed, or a symbol has no quote.
        """
        self._require_connection()
        symbols = [p.symbol for p in products]
        rows = self._quote_rows(symbols)
        missing = [s for s in symbols if s not in rows]
        if missing:
            raise RuntimeError(f"no quote for {', '.join(missing)}")
        return [yx.to_cj_snapshot(rows[s]) for s in symbols]

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        """Best bid and ask of the board-lot book (the quote table has one level)."""
        self._require_connection()
        rows = self._quote_rows([product.symbol])
        if product.symbol not in rows:
            raise RuntimeError(f"no quote for {product.symbol}")
        return yx.to_cj_bidask(rows[product.symbol])

    # ── orders ─────────────────────────────────────────────────────────────

    def _next_identify(self) -> int:
        with self._lock:
            self._identify += 1
            return self._identify

    def _send_stock_orders(self, stock_order) -> Any:
        orders = self.spark.List[self.spark.StockOrder]()
        orders.Add(stock_order)
        return self._call("SendStockOrder",
                          lambda: self.trader.SendStockOrder(self.account, orders, self._lang()))

    def place_order(self, order: Order) -> OrderResult:
        """Place an order on Yuanta (SendStockOrder).

        The order is checked against the odd-lot and board-lot rules first.
        The CJTrade id travels in ``BasketNo``; the reply's order number is
        stored as the broker id in the mirror database.

        Returns
        -------
        OrderResult
            ``linked_order`` is the CJTrade id. REJECTED, with the reason in
            ``message``, if the order breaks a rule or Yuanta refuses it.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        With ``environment="PROD"`` this places a REAL order. Writes to the mirror database.
        """
        self._require_connection()
        reason = yx.validate_order(order)
        if reason:
            return OrderResult(status=OrderStatus.REJECTED, message=reason,
                               metadata={"broker": yx.BROKER}, linked_order=order.id)
        try:
            obj = yx.fill_stock_order(self.spark.StockOrder(), order, self.account, self._next_identify())
            res = self._send_stock_orders(obj)
        except Exception as e:  # noqa: BLE001
            return OrderResult(status=OrderStatus.REJECTED, message=f"Order failed: {e}",
                               metadata={"broker": yx.BROKER}, linked_order=order.id)
        status = getattr(res, "ResultCount", None)
        rows = list(getattr(res, "ResultList", None) or [])
        row = rows[0] if rows else None
        if not yx.msg_ok(status) or row is None or int(getattr(row, "ReplyCode", 1) or 0) != 0:
            detail = " ".join(x for x in (
                yx.text(getattr(status, "MsgContent", "")),
                yx.text(getattr(row, "ErrNO", "")) if row is not None else "",
                yx.text(getattr(row, "Advisory", "")) if row is not None else "") if x)
            return OrderResult(status=OrderStatus.REJECTED, message=f"Order refused: {detail}",
                               metadata={"broker": yx.BROKER}, linked_order=order.id)
        key = yx.broker_key(row)
        shares = int(order.quantity) * (yx.LOT_SIZE if order.order_lot == OrderLot.Common else 1)
        with self._lock:
            self._orders[order.id] = {"key": key, "shares": shares, "filled": 0,
                                      "lot": order.order_lot, "symbol": order.product.symbol,
                                      "action": order.action, "price": order.price}
            self._status_cache[order.id] = OrderStatus.COMMITTED_WAIT_MATCHING
        order.broker = yx.BROKER
        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        if key:
            insert_new_ordermap_item_to_db(conn=self.db, cj_order_id=order.id,
                                           bkr_order_id=key, broker=yx.BROKER)
        return OrderResult(status=OrderStatus.COMMITTED_WAIT_MATCHING, message="",
                           metadata={"broker": yx.BROKER,
                                     "order_no": yx.text(getattr(row, "OrderNO", ""))},
                           linked_order=order.id)

    def _report(self) -> list:
        res = self._call("GetOrderTradeReport",
                         lambda: self.trader.GetOrderTradeReport(False, self.account, self._lang()))
        return list(getattr(res, "StkOrderList", None) or [])

    def _cj_id_for(self, row: Any) -> Optional[str]:
        """The CJTrade id of a report row: ``BasketNo`` (the id itself), else the order map."""
        tag = yx.text(getattr(row, "BasketNo", ""))
        with self._lock:
            if tag and tag in self._orders:
                return tag
            key = yx.broker_key(row)
            for cj_id, info in self._orders.items():
                if key and info.get("key") == key:
                    return cj_id
        if tag and len(tag) == 32:
            return tag
        key = yx.broker_key(row)
        return get_cj_order_id_from_db(conn=self.db, bkr_order_id=key) if key else None

    def sync_state(self) -> List[OrderResult]:
        """Refresh this adapter's orders from GetOrderTradeReport; return the open ones.

        Returns
        -------
        List[OrderResult]
            Not FILLED, CANCELLED or REJECTED. Empty if the query fails; the error is logged.

        Raises
        ------
        ConnectionError
            Not connected.
        """
        self._require_connection()
        try:
            rows = self._report()
        except Exception as e:  # noqa: BLE001
            log.error("sync_state failed: %s", e)
            return []
        still_open = []
        for row in rows:
            cj_id = self._cj_id_for(row)
            if not cj_id:
                continue
            status = yx.to_cj_status(row)
            with self._lock:
                info = self._orders.setdefault(cj_id, {})
                info.update(key=yx.broker_key(row), row=row,
                            filled=int(getattr(row, "OkQty", 0) or 0))
                self._status_cache[cj_id] = status
            update_order_status_to_db(conn=self.db, oid=cj_id, status=status.value)
            if status not in yx.FINAL_STATUSES:
                still_open.append(yx.to_cj_result(row, cj_order_id=cj_id))
        return still_open

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a CJTrade order (SendStockOrder with TradeKind 4).

        Returns
        -------
        OrderResult
            CANCELLED once Yuanta accepts the cancel; REJECTED with the reason
            if the order is unknown, already final, or the cancel is refused.

        Warnings
        --------
        With ``environment="PROD"`` this cancels a REAL order.
        """
        self._require_connection()
        try:
            row = next((r for r in self._report() if self._cj_id_for(r) == order_id), None)
            if row is None:
                raise LookupError(f"Order with ID {order_id} not found today")
            status = yx.to_cj_status(row)
            if status in yx.FINAL_STATUSES:
                raise RuntimeError(f"Cannot be cancelled because it is already {status.value}")
            if yx.text(getattr(row, "CancelFlag", "Y")) == "N":
                raise RuntimeError("Yuanta says this order cannot be cancelled now")
            obj = yx.fill_cancel_order(self.spark.StockOrder(), row, self.account, self._next_identify())
            res = self._send_stock_orders(obj)
            reply = next(iter(getattr(res, "ResultList", None) or []), None)
            if not yx.msg_ok(getattr(res, "ResultCount", None)) or reply is None \
                    or int(getattr(reply, "ReplyCode", 1) or 0) != 0:
                raise RuntimeError(" ".join(x for x in (
                    yx.text(getattr(getattr(res, "ResultCount", None), "MsgContent", "")),
                    yx.text(getattr(reply, "ErrNO", "")) if reply is not None else "",
                    yx.text(getattr(reply, "Advisory", "")) if reply is not None else "") if x)
                    or "cancel refused")
        except Exception as e:  # noqa: BLE001
            return OrderResult(status=OrderStatus.REJECTED, message=f"Failed to cancel order: {e}",
                               metadata={"broker": yx.BROKER, "error": str(e)}, linked_order=order_id)
        with self._lock:
            self._status_cache[order_id] = OrderStatus.CANCELLED
        update_order_status_to_db(conn=self.db, oid=order_id, status=OrderStatus.CANCELLED.value)
        result = yx.to_cj_result(row, cj_order_id=order_id)
        result.status = OrderStatus.CANCELLED
        return result

    def list_orders(self) -> List[Trade]:
        """Today's orders on the account, including ones placed elsewhere (``id='N/A'``)."""
        self._require_connection()
        try:
            rows = self._report()
        except Exception as e:  # noqa: BLE001
            log.error("list_orders failed: %s", e)
            return []
        return [yx.to_cj_trade(r, self._cj_id_for(r) or "N/A") for r in rows]

    # ── real-time reports ──────────────────────────────────────────────────

    def register_order_callback(self, callback: OrderCallback) -> None:
        """Call `callback` with an ``OrderEvent`` for every order and fill report.

        Yuanta subscribes the account to reports at login, so nothing else is needed.
        """
        with self._lock:
            self._order_callbacks.append(callback)

    def _on_real_report(self, value: Any) -> None:
        """RR_RealReport: one order report (RptType 50) or fill report (51) per row."""
        rows = list(getattr(value, "RealReportList", None) or []) if hasattr(value, "RealReportList") \
            else [value]
        for row in rows:
            try:
                self._handle_report(row)
            except Exception as e:  # noqa: BLE001
                log.exception("report handler failed: %s", e)

    def _handle_report(self, row: Any) -> None:
        rpt = int(getattr(row, "RptType", 0) or 0)
        if rpt not in (yx.RPT_STOCK_ORDER, yx.RPT_STOCK_FILL):
            return
        cj_id = self._cj_id_for(row)
        if not cj_id:
            return
        with self._lock:
            info = self._orders.setdefault(cj_id, {})
            old = self._status_cache.get(cj_id, OrderStatus.PLACED)
        filled_qty, filled_price, kind = 0, None, "order"
        if rpt == yx.RPT_STOCK_FILL:
            kind = "fill"
            fill_shares = int(getattr(row, "OrderQty", 0) or 0)
            filled_price = yx.num(getattr(row, "Price", 0)) or None
            with self._lock:
                info["filled"] = int(info.get("filled", 0) or 0) + fill_shares
                total, working = info["filled"], int(info.get("shares", 0) or 0)
            new = yx.by_quantity(total, working)
            filled_qty = yx.to_cj_quantity(row, fill_shares)
        else:
            new = yx.to_cj_status_from_report(row)
            if new is None:
                return
            if new == OrderStatus.COMMITTED_WAIT_MATCHING and info.get("filled"):
                new = OrderStatus.PARTIAL
        with self._lock:
            self._status_cache[cj_id] = new
            callbacks = list(self._order_callbacks)
        update_order_status_to_db(conn=self.db, oid=cj_id, status=new.value)
        action = yx.to_cj_action(getattr(row, "BS", ""))
        event = OrderEvent(
            event_type={OrderStatus.CANCELLED: EventType.ORDER_CANCELLED,
                        OrderStatus.REJECTED: EventType.ORDER_REJECTED}.get(
                new, EventType.ORDER_FILLED if kind == "fill" else EventType.ORDER_STATUS_CHANGE),
            timestamp=datetime.now(),
            order_id=cj_id,
            symbol=yx.text(getattr(row, "CompanyNo", "")),
            action=OrderAction(action) if action in ("BUY", "SELL") else None,
            quantity=yx.to_cj_quantity(row, info.get("shares") or getattr(row, "OrderQty", 0)),
            price=yx.num(getattr(row, "Price", 0)),
            old_status=old,
            new_status=new,
            filled_quantity=filled_qty,
            filled_price=filled_price,
            filled_value=filled_qty * filled_price if filled_price else None,
            broker_raw_data={"broker": yx.BROKER, "kind": kind, "key": yx.broker_key(row),
                             "yuanta_status": getattr(row, "OrderStatus", None),
                             "error_no": yx.text(getattr(row, "StkErrorNo", ""))},
        )
        for cb in callbacks:
            try:
                cb(event)
            except Exception as e:  # noqa: BLE001
                log.exception("order callback failed: %s", e)

    # ── clock and identity ─────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Whether the local time is on a weekday, 09:00-13:30. Holidays are not considered."""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        return now.replace(hour=9, minute=0, second=0, microsecond=0) <= now <= \
            now.replace(hour=13, minute=30, second=0, microsecond=0)

    def get_market_time(self) -> dict:
        """Live broker: market time is the local wall clock, at 1x, never paused."""
        now = datetime.now()
        return {"mock_current_time": now, "real_current_time": now,
                "mock_init_time": self._session_start, "real_init_time": self._session_start,
                "playback_speed": 1.0, "paused": False}

    def get_broker_name(self) -> str:
        """Return ``'yuanta'``."""
        return yx.BROKER

    # ── shortcuts ──────────────────────────────────────────────────────────

    def _shortcut(self, action: OrderAction, symbol: str, quantity: int, price: float,
                  intraday_odd: bool) -> OrderResult:
        order = Order(
            product=Product(type=ProductType.STOCK, exchange=Exchange.TSE, symbol=symbol),
            action=action, price=price, quantity=quantity,
            price_type=PriceType.LMT, order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common,
        )
        result = self.place_order(order)
        if result.status == OrderStatus.REJECTED:
            return result
        state = next((s for s in self.sync_state() if s.linked_order == order.id), None)
        if state is not None:
            result.status = state.status
        return result

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
        """Limit buy, ROD. Odd lots (shares) by default; ``intraday_odd=False`` for lots."""
        return self._shortcut(OrderAction.BUY, symbol, quantity, price, intraday_odd)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
        """Limit sell, ROD. Odd lots (shares) by default; ``intraday_odd=False`` for lots."""
        return self._shortcut(OrderAction.SELL, symbol, quantity, price, intraday_odd)
