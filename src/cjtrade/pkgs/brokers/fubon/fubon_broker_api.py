"""Broker API for Fubon Securities (富邦證券), built on the fubon_neo SDK.

Usage::

    from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

    client = AccountClient(BrokerType.FUBON, personal_id="A123456789",
                           api_key="...", cert_path="/path/to/A123456789.pfx",
                           cert_pass="...")
    client.connect()
    print(client.get_balance())

Testing in progress, use at your own risk: not yet run against a Fubon
account. Every order method acts on a real account: Fubon has no sandbox flag
in the SDK. Prices for bars come from a separate MarketData (``AccountClient(...,
market=...)``); this adapter serves quotes only.
"""
from __future__ import annotations

import threading
from datetime import date
from datetime import datetime
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs import paths
from cjtrade.pkgs.brokers.base_broker_api import BrokerAPIBase
from cjtrade.pkgs.brokers.fubon import _internal_func as fx
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
from fubon_neo.sdk import FubonSDK

log = get_logger("brokers.fubon")

OrderCallback = Callable[[OrderEvent], None]


def broker_key(result: Any) -> Optional[str]:
    """The id this adapter maps CJTrade orders to: ``<date>:<seq_no>``.

    ``seq_no`` (委託單流水序號) is assigned when the order is accepted and,
    unlike ``order_no``, is present on pre-market orders and in fill reports.
    It is only unique within a trading day, hence the date.
    """
    seq_no = getattr(result, "seq_no", None)
    if not seq_no:
        return None
    day = getattr(result, "date", None) or date.today().strftime("%Y/%m/%d")
    return f"{day}:{seq_no}"


class FubonBrokerAPI(BrokerAPIBase):
    """Broker API for Fubon, built on fubon_neo.

    Parameters
    ----------
    **config
        Required: ``personal_id`` (身分證字號), ``cert_path`` and one of
        ``api_key`` (API-key login) or ``password`` (account password).
        Optional: ``cert_pass`` (defaults to ``personal_id`` in the SDK),
        ``account`` (which stock account to trade when the login returns
        several; default the first), ``url`` (SDK server override),
        ``username``, ``mirror_db_path``.

    Raises
    ------
    ValueError
        A required config key is missing.

    Warnings
    --------
    Every order method acts on a REAL account.
    """

    def __init__(self, **config: Any):
        super().__init__(**config)
        missing = [k for k in ("personal_id", "cert_path") if not config.get(k)]
        if not (config.get("api_key") or config.get("password")):
            missing.append("api_key or password")
        if missing:
            raise ValueError(f"FubonBrokerAPI needs: {', '.join(missing)}")
        self.personal_id = config["personal_id"]
        self.api_key = config.get("api_key") or ""
        self.password = config.get("password") or ""
        self.cert_path = config["cert_path"]
        self.cert_pass = config.get("cert_pass") or None
        self.account_no = str(config.get("account") or "")
        self.username = config.get("username", "user999")
        self.db_path = config.get("mirror_db_path") or str(paths.mirror_db_path("fubon"))
        self.db = None
        self.sdk = FubonSDK(url=config["url"]) if config.get("url") else FubonSDK()
        self.account = None
        self._connected = False
        self._session_start = datetime.now()
        # CJTrade order id -> the latest Fubon OrderResult for it. cancel_order
        # needs that object, not an id. Touched from the SDK's callback thread.
        self._lock = threading.RLock()
        self._orders: Dict[str, Any] = {}
        self._order_callbacks: List[OrderCallback] = []
        self._status_cache: Dict[str, OrderStatus] = {}
        # Shares filled so far per CJTrade order, so a run of fill reports adds up.
        self._filled: Dict[str, int] = {}
        self._callbacks_installed = False

    # ── session ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Log in, pick the stock account and open the local mirror database.

        Returns
        -------
        bool
            True on success. A failed login is logged with Fubon's message
            and gives False.

        Warnings
        --------
        Makes network calls and opens (creating if needed) the mirror database file.
        """
        if self._connected:
            return True
        try:
            if self.api_key:
                res = self.sdk.apikey_login(self.personal_id, self.api_key,
                                            self.cert_path, self.cert_pass)
            else:
                res = self.sdk.login(self.personal_id, self.password,
                                     self.cert_path, self.cert_pass)
        except Exception as e:  # noqa: BLE001 - the SDK raises for transport errors
            log.error("login failed: %s", e)
            return False
        if not getattr(res, "is_success", False):
            log.error("login refused: %s", getattr(res, "message", res))
            return False
        self.account = self._pick_account(getattr(res, "data", None) or [])
        if self.account is None:
            log.error("login returned no stock account%s",
                      f" numbered {self.account_no}" if self.account_no else "")
            return False
        self.db = connect_sqlite(database=self.db_path)
        prepare_cjtrade_tables(conn=self.db)
        self._connected = True
        self._install_callbacks()
        return True

    def _pick_account(self, accounts: list):
        stock = [a for a in accounts if str(getattr(a, "account_type", "stock")).lower() == "stock"]
        if self.account_no:
            stock = [a for a in stock if str(getattr(a, "account", "")) == self.account_no]
        return stock[0] if stock else None

    def disconnect(self) -> None:
        """Log out and close the mirror database. Errors are logged, not raised."""
        try:
            if self._connected:
                self.sdk.logout()
        except Exception as e:  # noqa: BLE001
            log.error("logout failed: %s", e)
        finally:
            self._connected = False
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

    @staticmethod
    def _data(res: Any, what: str):
        """``res.data`` of a successful SDK call; raises with Fubon's message otherwise."""
        if not getattr(res, "is_success", False):
            raise RuntimeError(f"{what} failed: {getattr(res, 'message', res)}")
        return getattr(res, "data", None)

    # ── account ────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Bank balance of the settlement account (``bank_remain().balance``), in TWD.

        Raises
        ------
        ConnectionError
            Not connected.
        RuntimeError
            Fubon refused the query.
        """
        self._require_connection()
        data = self._data(self.sdk.accounting.bank_remain(self.account), "bank_remain")
        return fx.to_number(getattr(data, "balance", 0))

    def get_positions(self) -> List[Position]:
        """Holdings with cost and unrealised P&L, quantities in shares.

        Raises
        ------
        ConnectionError
            Not connected.
        RuntimeError
            Fubon refused the query.
        """
        self._require_connection()
        rows = self._data(self.sdk.accounting.unrealized_gains_and_loses(self.account),
                          "unrealized_gains_and_loses")
        return fx.to_cj_positions(rows)

    # ── quotes ─────────────────────────────────────────────────────────────

    def _quote(self, symbol: str, odd: bool = False):
        from fubon_neo.constant import MarketType
        market_type = MarketType.IntradayOdd if odd else MarketType.Common
        return self._data(self.sdk.stock.query_symbol_quote(self.account, symbol, market_type),
                          f"query_symbol_quote {symbol}")

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """Latest quote per product from ``stock.query_symbol_quote``.

        Raises
        ------
        ConnectionError
            Not connected.
        RuntimeError
            Fubon refused a query.
        """
        self._require_connection()
        return [fx.to_cj_snapshot(self._quote(p.symbol)) for p in products]

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        """Best bid and ask (one level) from ``stock.query_symbol_quote``."""
        self._require_connection()
        return fx.to_cj_bidask(self._quote(product.symbol, odd=intraday_odd))

    # ── orders ─────────────────────────────────────────────────────────────

    def place_order(self, order: Order) -> OrderResult:
        """Place an order on Fubon.

        The order is checked against Fubon's market-type rules first, then
        sent; the reply's ``<date>:<seq_no>`` is stored as the order's broker
        id in the mirror database.

        Returns
        -------
        OrderResult
            ``linked_order`` is the CJTrade order id. REJECTED, with the reason
            in ``message``, if the order breaks a rule or Fubon refuses it.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Places a REAL order on a real account and writes to the mirror database.
        """
        self._require_connection()
        reason = fx.validate_order(order)
        if reason:
            return OrderResult(status=OrderStatus.REJECTED, message=reason,
                               metadata={"broker": fx.BROKER}, linked_order=order.id)
        try:
            res = self.sdk.stock.place_order(self.account, fx.to_fubon_order(order))
        except Exception as e:  # noqa: BLE001
            return OrderResult(status=OrderStatus.REJECTED, message=f"Order failed: {e}",
                               metadata={"broker": fx.BROKER}, linked_order=order.id)
        if not getattr(res, "is_success", False) or getattr(res, "data", None) is None:
            return OrderResult(status=OrderStatus.REJECTED,
                               message=f"Order refused: {getattr(res, 'message', res)}",
                               metadata={"broker": fx.BROKER}, linked_order=order.id)
        result = res.data
        key = broker_key(result)
        with self._lock:
            self._orders[order.id] = result
            self._status_cache[order.id] = fx.to_cj_status(result)
        order.broker = fx.BROKER
        insert_new_order_to_db(conn=self.db, username=self.username, order=order)
        if key:
            insert_new_ordermap_item_to_db(conn=self.db, cj_order_id=order.id,
                                           bkr_order_id=key, broker=fx.BROKER)
        else:
            log.warning("order %s has no seq_no; it can only be found by its user_def", order.id)
        return fx.to_cj_result(result, cj_order_id=order.id)

    def _today_results(self) -> list:
        return self._data(self.sdk.stock.get_order_results(self.account), "get_order_results") or []

    def _cj_id_for(self, result: Any) -> Optional[str]:
        """The CJTrade id of a Fubon OrderResult: memory first, then the order
        map, then the ``user_def`` tag this adapter sends with every order."""
        key = broker_key(result)
        with self._lock:
            for cj_id, known in self._orders.items():
                if key and broker_key(known) == key:
                    return cj_id
        if key:
            cj_id = get_cj_order_id_from_db(conn=self.db, bkr_order_id=key)
            if cj_id:
                return cj_id
        tag = getattr(result, "user_def", None)
        if tag:
            with self._lock:
                for cj_id in self._orders:
                    if cj_id.startswith(str(tag)):
                        return cj_id
        return None

    def sync_state(self) -> List[OrderResult]:
        """Refresh every order this adapter placed today; return the open ones.

        Updates the in-memory map and the mirror database. Orders placed
        outside CJTrade are left out.

        Returns
        -------
        List[OrderResult]
            Open orders (not FILLED, CANCELLED or REJECTED). Empty if the
            query fails; the error is logged.

        Raises
        ------
        ConnectionError
            Not connected.
        """
        self._require_connection()
        try:
            results = self._today_results()
        except Exception as e:  # noqa: BLE001
            log.error("sync_state failed: %s", e)
            return []
        still_open = []
        for result in results:
            cj_id = self._cj_id_for(result)
            if not cj_id:
                continue
            status = fx.to_cj_status(result)
            with self._lock:
                self._orders[cj_id] = result
                self._status_cache[cj_id] = status
                self._filled[cj_id] = int(getattr(result, "filled_qty", 0) or 0)
            update_order_status_to_db(conn=self.db, oid=cj_id, status=status.value)
            if status not in fx.FINAL_STATUSES:
                still_open.append(fx.to_cj_result(result, cj_order_id=cj_id))
        return still_open

    def _find_result(self, order_id: str):
        """The current Fubon OrderResult of a CJTrade order, refreshed from Fubon."""
        for result in self._today_results():
            if self._cj_id_for(result) == order_id:
                with self._lock:
                    self._orders[order_id] = result
                return result
        return None

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a CJTrade order on Fubon.

        Returns
        -------
        OrderResult
            CANCELLED, or REJECTED with the reason if the order is unknown,
            already final, or Fubon refuses.

        Raises
        ------
        ConnectionError
            Not connected.

        Warnings
        --------
        Cancels a REAL order and writes to the mirror database.
        """
        self._require_connection()
        try:
            target = self._find_result(order_id)
            if target is None:
                raise LookupError(f"Order with ID {order_id} not found today")
            status = fx.to_cj_status(target)
            if status in fx.FINAL_STATUSES:
                raise RuntimeError(f"Cannot be cancelled because it is already {status.value}")
            data = self._data(self.sdk.stock.cancel_order(self.account, target), "cancel_order")
            if data is None:
                raise RuntimeError("cancel_order returned no order")
            # A blocking cancel answers with the order at status 30 (or 40 if
            # part of it had filled). Anything else is reported as it is and
            # settled by the next sync_state.
            result = fx.to_cj_result(data, cj_order_id=order_id)
            with self._lock:
                self._orders[order_id] = data
                self._status_cache[order_id] = result.status
            update_order_status_to_db(conn=self.db, oid=order_id, status=result.status.value)
            return result
        except Exception as e:  # noqa: BLE001
            return OrderResult(status=OrderStatus.REJECTED,
                               message=f"Failed to cancel order: {e}",
                               metadata={"broker": fx.BROKER, "error": str(e)},
                               linked_order=order_id)

    def list_orders(self) -> List[Trade]:
        """Today's orders on the account, including ones placed outside CJTrade
        (their ``id`` is ``'N/A'``).

        Returns
        -------
        List[Trade]
            Empty if the query fails; the error is logged.

        Raises
        ------
        ConnectionError
            Not connected.
        """
        self._require_connection()
        try:
            results = self._today_results()
        except Exception as e:  # noqa: BLE001
            log.error("list_orders failed: %s", e)
            return []
        return [fx.to_cj_trade(r, self._cj_id_for(r) or "N/A") for r in results]

    # ── fill and order reports ─────────────────────────────────────────────

    def register_order_callback(self, callback: OrderCallback) -> None:
        """Call `callback` with an ``OrderEvent`` on every order or fill report.

        Reports for orders placed outside CJTrade are ignored.
        """
        with self._lock:
            self._order_callbacks.append(callback)
        self._install_callbacks()

    def _install_callbacks(self) -> None:
        if self._callbacks_installed or not self._connected:
            return
        self.sdk.set_on_order(self._on_order)
        self.sdk.set_on_order_changed(self._on_order)
        self.sdk.set_on_filled(self._on_filled)
        self.sdk.set_on_event(self._on_event)
        self._callbacks_installed = True

    def _emit(self, cj_id: str, result: Any, new_status: OrderStatus,
              filled_qty: int = 0, filled_price: Optional[float] = None,
              kind: str = "order", raw: Any = None) -> None:
        with self._lock:
            old = self._status_cache.get(cj_id, OrderStatus.PLACED)
            self._status_cache[cj_id] = new_status
            callbacks = list(self._order_callbacks)
        update_order_status_to_db(conn=self.db, oid=cj_id, status=new_status.value)
        action = fx.to_cj_action(getattr(result, "buy_sell", None))
        qty_shares = getattr(result, "after_qty", None) or getattr(result, "quantity", None) \
            or getattr(result, "filled_qty", 0)
        event = OrderEvent(
            event_type={OrderStatus.CANCELLED: EventType.ORDER_CANCELLED,
                        OrderStatus.REJECTED: EventType.ORDER_REJECTED}.get(
                new_status, EventType.ORDER_FILLED if kind == "fill" else EventType.ORDER_STATUS_CHANGE),
            timestamp=datetime.now(),
            order_id=cj_id,
            symbol=str(getattr(result, "stock_no", "") or ""),
            action=OrderAction(action) if action in ("BUY", "SELL") else None,
            quantity=fx.to_cj_quantity(result, qty_shares),
            price=float(getattr(result, "after_price", None) or getattr(result, "price", None)
                        or getattr(result, "filled_price", 0) or 0.0),
            old_status=old,
            new_status=new_status,
            filled_quantity=filled_qty,
            filled_price=filled_price,
            filled_value=filled_qty * filled_price if filled_price else None,
            broker_raw_data={"broker": fx.BROKER, "kind": kind, "key": broker_key(result),
                             "raw": str(raw if raw is not None else result)},
        )
        for cb in callbacks:
            try:
                cb(event)
            except Exception as e:  # noqa: BLE001
                log.exception("order callback failed: %s", e)

    def _on_order(self, err: Any, content: Any) -> None:
        """Order accepted, changed, cancelled or failed (``set_on_order`` /
        ``set_on_order_changed``); `content` is an OrderResult."""
        if err:
            log.warning("order report error: %s", err)
        if content is None:
            return
        try:
            cj_id = self._cj_id_for(content)
            if not cj_id:
                return
            with self._lock:
                self._orders[cj_id] = content
                self._filled[cj_id] = max(self._filled.get(cj_id, 0),
                                          int(getattr(content, "filled_qty", 0) or 0))
            self._emit(cj_id, content, fx.to_cj_status(content),
                       filled_qty=int(getattr(content, "filled_qty", 0) or 0), raw=content)
        except Exception as e:  # noqa: BLE001
            log.exception("order report handler failed: %s", e)

    def _on_filled(self, err: Any, content: Any) -> None:
        """A fill (``set_on_filled``); `content` is a FilledData.

        A fill report says how much traded, not whether the order is done, so
        the new status is FILLED only once the order's filled quantity reaches
        its working quantity; until then it is PARTIAL.
        """
        if err:
            log.warning("fill report error: %s", err)
        if content is None:
            return
        try:
            cj_id = self._cj_id_for(content)
            if not cj_id:
                return
            fill_shares = int(getattr(content, "filled_qty", 0) or 0)
            with self._lock:
                known = self._orders.get(cj_id)
                before = self._filled.get(
                    cj_id, int(getattr(known, "filled_qty", 0) or 0) if known is not None else 0)
                total = before + fill_shares
                self._filled[cj_id] = total
            working = int(getattr(known, "after_qty", 0) or 0) if known is not None else 0
            status = OrderStatus.FILLED if working and total >= working else OrderStatus.PARTIAL
            ref = known if known is not None else content
            self._emit(cj_id, ref, status,
                       filled_qty=fx.to_cj_quantity(ref, fill_shares),
                       filled_price=fx.to_number(getattr(content, "filled_price", None)) or None,
                       kind="fill", raw=content)
        except Exception as e:  # noqa: BLE001
            log.exception("fill report handler failed: %s", e)

    def _on_event(self, err: Any, content: Any) -> None:
        """Connection and session events; logged only."""
        log.info("fubon event: %s %s", err, content)

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
        """Return ``'fubon'``."""
        return fx.BROKER

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
        """Limit buy, ROD. Odd lots (shares) by default; ``intraday_odd=False`` for lots.

        Warnings
        --------
        Places a REAL order on a real account.
        """
        return self._shortcut(OrderAction.BUY, symbol, quantity, price, intraday_odd)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
        """Limit sell, ROD. Odd lots (shares) by default; ``intraday_odd=False`` for lots.

        Warnings
        --------
        Places a REAL order on a real account.
        """
        return self._shortcut(OrderAction.SELL, symbol, quantity, price, intraday_odd)
