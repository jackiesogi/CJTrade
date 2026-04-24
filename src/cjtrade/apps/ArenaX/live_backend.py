from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.market_data import ArenaX_Market
from cjtrade.apps.ArenaX.market_data import ArenaX_RealMarket
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot


class ArenaX_Backend_PaperTrade(ArenaX_BackendBase):
	def __init__(
		self,
		state_file: str = "live_account_state.json",
		real_account: Optional[AccountClient] = None,
		playback_speed: float = 1.0,
		**kwargs
	) -> None:
		super().__init__(
			state_file=state_file,
			real_account=real_account,
			playback_speed=playback_speed,
			num_days_preload=0,
			skip_data_preload=True,
		)
		if real_account:
			self.market = ArenaX_RealMarket(real_account=real_account)
		else:
			self.market = ArenaX_Market(real_account=real_account, price_db_path=self.price_db_path)
			if hasattr(self.market, "set_playback_speed"):
				self.market.set_playback_speed(playback_speed)
		if self.real_account and not self.real_account.is_connected():
			self.real_account.connect()
		self._kbar_buffer: Dict[str, List[Kbar]] = {}

	def _sync_with_real_account(self) -> None:
		if not self.real_account:
			return

		try:
			if not self.real_account.is_connected():
				self.real_account.connect()

			self.account_state.balance = self.real_account.get_balance()
			real_positions = self.real_account.get_positions()

			if not real_positions:
				self.account_state.positions = []
				return

			for pos in real_positions:
				self.account_state.fill_history.append({
					"id": f"init_{pos.symbol}_{int(datetime.now().timestamp())}",
					"order_id": "manual_sync",
					"symbol": pos.symbol,
					"action": "BUY",
					"quantity": pos.quantity,
					"price": pos.avg_cost,
					"time": "initial_sync",
				})

			self._reconstruct_positions_from_history()
			self._update_position_prices()
		except Exception as exc:
			print(f"[PaperTrade] Error syncing with real account: {exc}")

	def _sync_with_mock_account_file(self) -> None:
		super()._sync_with_mock_account_file()
		if self.account_state.positions:
			self._update_position_prices()

	def snapshot(self, symbol: str) -> Snapshot:
		self._check_if_any_order_filled()
		if self.real_account:
			if not self.real_account.is_connected():
				self.real_account.connect()
			return self.real_account.get_snapshots([Product(symbol=symbol)])[0]
		return super().snapshot(symbol)

	def _refresh_kbar_buffer(self, symbol: str) -> None:
		if not self.real_account:
			return

		today = datetime.now().strftime("%Y-%m-%d")
		tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
		try:
			try:
				kbars = self.real_account.get_kbars(
					Product(symbol=symbol),
					start=today,
					end=tomorrow,
					interval="1m",
				)
			except TypeError:
				kbars = self.real_account.get_kbars(
					Product(symbol=symbol),
					today,
					tomorrow,
					"1m",
				)
			self._kbar_buffer[symbol] = kbars if kbars else []
		except Exception as exc:
			print(f"[PaperTrade] Failed to refresh kbar buffer for {symbol}: {exc}")
			self._kbar_buffer.setdefault(symbol, [])

	def _check_if_any_order_filled(self) -> bool:
		if not self.real_account:
			return super()._check_if_any_order_filled()

		if not self.account_state.orders_committed:
			return False

		symbols = {order.product.symbol for order in self.account_state.orders_committed}
		for symbol in symbols:
			self._refresh_kbar_buffer(symbol)

		committed_copy = list(self.account_state.orders_committed)
		any_filled = False

		for order in committed_copy:
			target_price = order.price
			last_check_time = order.opt_field.get("last_check_for_fill", order.created_at)

			kbars = self._kbar_buffer.get(order.product.symbol, [])
			new_kbars = [kbar for kbar in kbars if kbar.timestamp > last_check_time]

			if not new_kbars:
				continue

			order.opt_field["last_check_for_fill"] = new_kbars[-1].timestamp

			fill_kbar = None
			for kbar in new_kbars:
				if order.action == OrderAction.BUY and kbar.close <= target_price:
					fill_kbar = kbar
					break
				if order.action == OrderAction.SELL and kbar.close >= target_price:
					fill_kbar = kbar
					break

			if fill_kbar is None:
				continue

			try:
				self.account_state.orders_filled.append(order)
				if order in self.account_state.orders_committed:
					self.account_state.orders_committed.remove(order)
				self.account_state.all_order_status[order.id] = OrderStatus.FILLED

				qty_signed = order.quantity if order.action == OrderAction.BUY else -order.quantity
				self.account_state.balance -= (qty_signed * order.price)

				self.account_state.fill_history.append({
					"id": f"fill_{order.id}_{int(datetime.now().timestamp())}",
					"order_id": order.id,
					"symbol": order.product.symbol,
					"action": order.action.value,
					"quantity": qty_signed,
					"price": order.price,
					"time": fill_kbar.timestamp.isoformat(),
				})

				self._reconstruct_positions_from_history()
				any_filled = True
			except Exception as exc:
				print(f"[PaperTrade] Error filling order {order.id}: {exc}")

		return any_filled

	def _trigger_order_matching(self) -> None:
		self._check_if_any_order_filled()
