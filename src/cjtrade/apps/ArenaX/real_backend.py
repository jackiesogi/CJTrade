from datetime import datetime
from typing import List
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.market_data import ArenaX_RealMarket
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NEGATIVE_PRICE
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NEGATIVE_QUANTITY
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NOT_FOUND_FOR_COMMIT
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.trade import Trade


class ArenaX_Backend_RealTrade(ArenaX_BackendBase):
    """ArenaX backend that proxies all operations to a live real broker.

    The ArenaX HTTP server uses this backend when launched in 'live' mode.
    Every operation (snapshot, kbars, place/cancel order, balance, positions)
    is delegated to the injected ``real_account`` (AccountClient).  The local
    ``account_state`` is kept in sync so that the server's in-memory state
    matches the broker at all times.

    Data-format notes
    -----------------
    * ``real_account.get_positions()``  → ``List[Position]``          (direct use)
    * ``real_account.get_snapshots()``  → ``List[Snapshot]``          (direct use)
    * ``real_account.list_orders()``    → ``List[Trade]``             (direct use)
    * ``real_account.sync_state()``     → ``List[OrderResult]``       (used for fill polling)
    * ``real_account.place_order()``    → ``OrderResult``             (direct return)
    * ``real_account.cancel_order()``   → ``OrderResult``             (direct return)
    * ``real_account.get_kbars()``      → ``List[Kbar]``              (direct return)
    """

    def __init__(
        self,
        state_file: str = "real_account_state.json",   # kept for interface compat, not persisted
        real_account: Optional[AccountClient] = None,
        playback_speed: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(
            state_file=state_file,
            real_account=real_account,
            playback_speed=playback_speed,
            num_days_preload=0,
            skip_data_preload=True,
        )
        if not real_account:
            raise ValueError("real_account is required for ArenaX_Backend_RealTrade")

        self.market = ArenaX_RealMarket(real_account=real_account)

        if self.real_account and not self.real_account.is_connected():
            self.real_account.connect()

    # ─── Internal sync helpers ─────────────────────────────────────────────────

    def _sync_with_real_account(self) -> None:
        """Pull balance + positions from real broker into local account_state."""
        if not self.real_account:
            return

        try:
            if not self.real_account.is_connected():
                self.real_account.connect()

            self.account_state.balance = self.real_account.get_balance()
            real_positions = self.real_account.get_positions()
            self.account_state.positions = real_positions or []

            # Seed fill_history so _reconstruct_positions_from_history stays consistent
            for pos in (real_positions or []):
                self.account_state.fill_history.append({
                    "id": f"init_{pos.symbol}_{int(datetime.now().timestamp())}",
                    "order_id": "manual_sync",
                    "symbol": pos.symbol,
                    "action": "BUY",
                    "quantity": pos.quantity,
                    "price": pos.avg_cost,
                    "time": "initial_sync",
                })
        except Exception as exc:
            print(f"[RealTrade] Error syncing with real account: {exc}")

    def _check_if_any_order_filled(self) -> bool:
        """Poll real broker for fills and update local order/balance state."""
        if not self.account_state.orders_committed:
            return False
        if not self.real_account:
            return False

        try:
            if not self.real_account.is_connected():
                self.real_account.connect()
            # Returns List[OrderResult]; each result carries linked_order = order_id
            broker_results: List[OrderResult] = self.real_account.sync_state()
        except Exception as exc:
            print(f"[RealTrade] Error polling broker for fills: {exc}")
            return False

        result_by_id = {
            r.linked_order: r
            for r in (broker_results or [])
            if r and r.linked_order
        }

        for order in list(self.account_state.orders_committed):
            broker_result = result_by_id.get(order.id)
            if not broker_result:
                continue

            if broker_result.status == OrderStatus.FILLED:
                self.account_state.orders_committed.remove(order)
                self.account_state.orders_filled.append(order)
                self.account_state.all_order_status[order.id] = OrderStatus.FILLED

                fill_price = (
                    broker_result.metadata.get("fill_price", order.price)
                    if broker_result.metadata
                    else order.price
                )
                qty_signed = order.quantity if order.action == OrderAction.BUY else -order.quantity
                self.account_state.balance -= qty_signed * fill_price

                self.account_state.fill_history.append({
                    "id": f"fill_{order.id}_{int(datetime.now().timestamp())}",
                    "order_id": order.id,
                    "symbol": order.product.symbol,
                    "action": order.action.value,
                    "quantity": qty_signed,
                    "price": fill_price,
                    "time": datetime.now().isoformat(),
                    "session_id": order.opt_field.get("session_id") if order.opt_field else None,
                })
                print(f"[RealTrade] Order filled: {order.id} @ {fill_price}")

            elif broker_result.status == OrderStatus.CANCELLED:
                self.account_state.orders_committed.remove(order)
                self.account_state.orders_cancelled.append(order)
                self.account_state.all_order_status[order.id] = OrderStatus.CANCELLED
                print(f"[RealTrade] Order cancelled by broker: {order.id}")

        return True

    # ─── Account queries ───────────────────────────────────────────────────────

    def account_balance(self) -> float:
        """Fetch live balance from real broker; fall back to cached value on error."""
        try:
            balance = self.real_account.get_balance()
            self.account_state.balance = balance
            return balance
        except Exception as exc:
            print(f"[RealTrade] Error fetching balance: {exc}")
            return self.account_state.balance

    def list_positions(self) -> List[Position]:
        """Fetch live positions from real broker; fall back to cached value on error."""
        try:
            positions = self.real_account.get_positions()
            self.account_state.positions = positions or []
            return self.account_state.positions
        except Exception as exc:
            print(f"[RealTrade] Error fetching positions: {exc}")
            return self.account_state.positions

    # ─── Market data ───────────────────────────────────────────────────────────

    def snapshot(self, symbol: str) -> Snapshot:
        """Fetch live snapshot from real broker."""
        try:
            if not self.real_account.is_connected():
                self.real_account.connect()
            snapshots = self.real_account.get_snapshots([Product(symbol=symbol)])
            if snapshots:
                return snapshots[0]
        except Exception as exc:
            print(f"[RealTrade] Error fetching snapshot for {symbol}: {exc}")
        return self._create_fallback_snapshot(symbol, datetime.now())

    def kbars(self, symbol: str, start: str, end: str, interval: str = "1m") -> List[Kbar]:
        """Fetch kbars from real broker."""
        try:
            return self.real_account.get_kbars(
                product=Product(symbol=symbol),
                start=start,
                end=end,
                interval=interval,
            ) or []
        except Exception as exc:
            print(f"[RealTrade] Error fetching kbars for {symbol} [{start}~{end}]: {exc}")
            return []

    # ─── Trade operations ──────────────────────────────────────────────────────

    def list_trades(self) -> List[Trade]:
        """Return order list from real broker; fall back to local state on error."""
        try:
            broker_trades = self.real_account.list_orders()
            if broker_trades is not None:
                return broker_trades
        except Exception as exc:
            print(f"[RealTrade] Error listing broker trades: {exc}")
        # Fallback: build Trade objects from locally tracked orders (same as base class)
        return super().list_trades()

    def place_order(self, order: Order) -> OrderResult:
        """Validate then forward order to real broker; track locally if accepted."""
        if not self._is_valid_price(order):
            return REJECTED_ORDER_NEGATIVE_PRICE(order, metadata=order.opt_field)
        if not self._is_valid_quantity(order):
            return REJECTED_ORDER_NEGATIVE_QUANTITY(order, metadata=order.opt_field)

        try:
            if not self.real_account.is_connected():
                self.real_account.connect()
            result = self.real_account.place_order(order)
        except Exception as exc:
            print(f"[RealTrade] Error placing order: {exc}")
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Broker error: {exc}",
                metadata=order.opt_field or {},
                linked_order=order.id,
            )

        # Track locally so sync_state / cancel_order can follow up
        if result.status != OrderStatus.REJECTED:
            order.opt_field = order.opt_field or {}
            order.opt_field["last_check_for_fill"] = datetime.now()
            self.account_state.orders_placed.append(order)
            self.account_state.all_order_status[order.id] = result.status

        return result

    def cancel_order(self, order_id: str) -> OrderResult:
        """Forward cancel request to real broker and clean up local state."""
        try:
            if not self.real_account.is_connected():
                self.real_account.connect()
            result = self.real_account.cancel_order(order_id)
        except Exception as exc:
            print(f"[RealTrade] Error cancelling order {order_id}: {exc}")
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Broker error: {exc}",
                linked_order=order_id,
            )

        if result.status == OrderStatus.CANCELLED:
            for lst in (self.account_state.orders_placed, self.account_state.orders_committed):
                order_to_cancel = next((o for o in lst if o.id == order_id), None)
                if order_to_cancel:
                    lst.remove(order_to_cancel)
                    self.account_state.orders_cancelled.append(order_to_cancel)
                    break
            self.account_state.all_order_status[order_id] = OrderStatus.CANCELLED

        return result

    def sync_state(self, order_id: str) -> OrderResult:
        """Move a placed order to committed state, then eagerly poll broker for fills.

        This mirrors the base-class contract (placed → committed) while also
        triggering an immediate fill-check so market orders that fill instantly
        are reflected right away.
        """
        order = next((o for o in self.account_state.orders_placed if o.id == order_id), None)
        if not order:
            return REJECTED_ORDER_NOT_FOUND_FOR_COMMIT(order_id)

        self.account_state.orders_placed.remove(order)
        self.account_state.orders_committed.append(order)
        self.account_state.all_order_status[order.id] = OrderStatus.COMMITTED_WAIT_MATCHING

        # Eagerly poll for immediate fills (e.g. market orders)
        self._check_if_any_order_filled()

        final_status = self.account_state.all_order_status.get(
            order.id, OrderStatus.COMMITTED_WAIT_MATCHING
        )
        return OrderResult(
            status=final_status,
            message="Order committed and polled for immediate fill.",
            metadata={"market_open": self.market.is_market_open()},
            linked_order=order.id,
        )
