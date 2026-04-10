import json
import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

import pandas as pd
import yfinance as yf
from cjtrade.apps.ArenaX.oder_result_helper import CANCELLED_ORDER_STANDARD
from cjtrade.apps.ArenaX.oder_result_helper import COMMITTED_ORDER_STANDARD
from cjtrade.apps.ArenaX.oder_result_helper import PLACED_ORDER_STANDARD
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_EXCEED_TRADING_LIMIT
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_HAS_BEEN_FILLED
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NEGATIVE_PRICE
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NEGATIVE_QUANTITY
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NOT_FOUND_FOR_CANCEL
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NOT_FOUND_FOR_COMMIT
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NOT_SUFFICIENT_BALANCE
from cjtrade.apps.ArenaX.oder_result_helper import REJECTED_ORDER_NOT_SUFFICIENT_STOCK
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.kbar import Kbar
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
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.trade import Trade

NOT_AVAILABLE_FOR_THIS_BACKEND = None
PLEASE_DEFINE_THIS_PARAM_IN_SUBCLASS = None

# ArenaX_BrokerSideServer.start() (for lifetime management)
#      |
#      v
# 3 kinds of ArenaX_Backend (for all necessary backend simulation)

# hist / live / none
# mode = price_data_src + use_case
# hist: (real_account + playback_speed + state_file + num_days_preload) + start/stop
# live: (real_account + state_file) + start/stop
# none: (playback_speed + state_file + num_days_preload) + start/stop
@dataclass
class ArenaX_AccountState:
    balance: float = 0.0
    initial_balance: float = 0.0          # set once at login; never mutated afterwards
    positions: List[object] = None
    orders_placed: List[object] = None
    orders_committed: List[object] = None
    orders_filled: List[object] = None
    orders_cancelled: List[object] = None
    all_order_status: Dict[str, object] = None
    fill_history: List[Dict] = None

    def __post_init__(self) -> None:
        self.positions = self.positions or []
        self.orders_placed = self.orders_placed or []
        self.orders_committed = self.orders_committed or []
        self.orders_filled = self.orders_filled or []
        self.orders_cancelled = self.orders_cancelled or []
        self.all_order_status = self.all_order_status or {}
        self.fill_history = self.fill_history or []


class ArenaX_BackendBase:
    def __init__(
        self,
        state_file: str = "mock_account_state.json",
        real_account: Optional[AccountClient] = None,
        playback_speed: float = 1.0,
        num_days_preload: int = 3,
        skip_data_preload: bool = False,
        initial_balance: float = 0.0,
    ) -> None:
        # print(f"num_days_preload: {num_days_preload}")
        self.account_state_default_file = state_file
        self.real_account = real_account
        if self.real_account and not self.real_account.is_connected():
            self.real_account.connect()  # Early connection for fetching data
        self.playback_speed = playback_speed
        self.num_days_preload = num_days_preload
        self.skip_data_preload = skip_data_preload
        self._connected = False
        self._initial_balance_override = initial_balance  # stored for use in login()
        self.account_state = ArenaX_AccountState()

    # NOTE: login() affect whether the account state is synced and whether the flag _connected is set.
    def login(self) -> bool:
        try:
            self._connected = True

            if self.real_account and not os.path.exists(self.account_state_default_file):
                print('sync with real account')
                self._sync_with_real_account()
            else:
                print('sync with mock account file')
                self._sync_with_mock_account_file()

            # Stamp initial_balance once per session (after state is loaded so we
            # can fall back to the loaded balance when no explicit override is given).
            if self._initial_balance_override > 0:
                self.account_state.initial_balance = self._initial_balance_override
            elif self.account_state.initial_balance == 0.0:
                # First run: treat the starting cash as initial_balance
                self.account_state.initial_balance = self.account_state.balance

            print("Simulation environment started")
            return True
        except Exception as e:
            print(f"Failed to start simulation environment: {e}")
            self._connected = False
            return False

    def logout(self) -> None:
        if self.real_account:
            self.real_account.disconnect()
        with open(self.account_state_default_file, 'w') as f:
            data = self._serialize_state_to_json()
            json.dump(data, f, indent=4)
        self._connected = False
        print("Simulation environment stopped")

    def is_connected(self) -> bool:
        return self._connected

    def account_balance(self) -> float:
        return self.account_state.balance

    def list_positions(self) -> List[Position]:
        self._reconstruct_positions_from_history()
        self._update_position_prices()
        return self.account_state.positions

    def kbars_yf(self, symbol: str, start: str, end: str, interval: str = "1m") -> List[Kbar]:
        yf_symbol = f"{symbol}.TW"

        try:
            data = yf.download(
                yf_symbol,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
            )

            if data.empty:
                print(f"No data available for {symbol} in range {start} to {end}")
                return []

            if not isinstance(data.index, pd.DatetimeIndex):
                data.index = pd.to_datetime(data.index)
            if data.index.tz is not None:
                if str(data.index.tz) in ["UTC", "UTC+00:00"]:
                    import pytz

                    taiwan_tz = pytz.timezone("Asia/Taipei")
                    data.index = data.index.tz_convert(taiwan_tz).tz_localize(None)
                else:
                    data.index = data.index.tz_localize(None)

            kbars = []
            for timestamp, row in data.iterrows():
                kbar = Kbar(
                    timestamp=timestamp.to_pydatetime(),
                    open=round(row["Open"].item(), 2),
                    high=round(row["High"].item(), 2),
                    low=round(row["Low"].item(), 2),
                    close=round(row["Close"].item(), 2),
                    volume=int(row["Volume"].item()),
                )
                kbars.append(kbar)

            return kbars

        except Exception as exc:
            print(f"Error loading kbars for {symbol}: {exc}")
            return []

    def kbars(self, symbol: str, start: str, end: str, interval: str = "1m") -> List[Kbar]:
        """Fetch kbars: first try price_db, then fill gaps from broker.

        This hybrid approach reduces broker API calls by leveraging cached local data,
        while ensuring we have the complete requested range by fetching missing pieces.
        """
        from datetime import datetime as dt
        from cjtrade.pkgs.db.db_api import compute_missing_ranges

        # Parse date range
        try:
            start_dt = dt.strptime(start, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
            end_dt = dt.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except Exception as e:
            print(f"Error parsing date range: {e}")
            return []

        # Try to get cached data from price_db if available
        cached_kbars = []
        if hasattr(self, 'market') and hasattr(self.market, 'price_db'):
            try:
                cached_kbars = self.market.price_db.get_price(
                    symbol=symbol,
                    timeframe=interval,
                    start_ts=start_dt,
                    end_ts=end_dt
                )
                print(f"[kbars] Found {len(cached_kbars)} cached kbars for {symbol} [{start} to {end}]")
            except Exception as e:
                print(f"[kbars] Error retrieving from price_db: {e}")

        # Check what ranges are missing
        missing_ranges = []
        if hasattr(self, 'market') and hasattr(self.market, 'price_db'):
            try:
                s_epoch = int(start_dt.timestamp())
                e_epoch = int(end_dt.timestamp())
                missing_ranges = compute_missing_ranges(
                    self.market.price_db.conn,
                    symbol,
                    interval,
                    s_epoch,
                    e_epoch
                )
                print(f"[kbars] Missing ranges for {symbol}: {len(missing_ranges)} gaps")
            except Exception as e:
                print(f"[kbars] Error computing missing ranges: {e}")
                # If we can't check coverage, fetch all from broker as fallback
                missing_ranges = [(int(start_dt.timestamp()), int(end_dt.timestamp()))]
        else:
            # No price_db available, fetch all from broker
            missing_ranges = [(int(start_dt.timestamp()), int(end_dt.timestamp()))]

        # Fetch missing ranges from broker
        broker_kbars = []
        if missing_ranges and self.real_account:
            try:
                for start_epoch, end_epoch in missing_ranges:
                    range_start = dt.fromtimestamp(start_epoch).strftime("%Y-%m-%d")
                    range_end = dt.fromtimestamp(end_epoch).strftime("%Y-%m-%d")
                    print(f"[kbars] Fetching from broker: {symbol} [{range_start} to {range_end}]")

                    # TODO: check if the backend real broker api support specified interval
                    fetched = self.real_account.get_kbars(
                        start=range_start,
                        end=range_end,
                        product=Product(symbol=symbol),
                        interval=interval
                    )

                    broker_kbars.extend(fetched)

                    # Cache the fetched data
                    if hasattr(self, 'market') and hasattr(self.market, 'price_db'):
                        try:
                            self.market.price_db.insert_prices_batch(
                                symbol=symbol,
                                kbars=fetched,
                                timeframe=interval,
                                source="broker_api",
                                overwrite=False
                            )
                            self.market.price_db.record_coverage(
                                symbol=symbol,
                                timeframe=interval,
                                start_ts=dt.strptime(range_start, "%Y-%m-%d"),
                                end_ts=dt.strptime(range_end, "%Y-%m-%d"),
                                source="broker_api"
                            )
                        except Exception as e:
                            print(f"[kbars] Error caching fetched data: {e}")

            except Exception as exc:
                print(f"[kbars] Error fetching from broker for {symbol}: {exc}")
                # Fallback: return cached data even if incomplete
                if cached_kbars:
                    return cached_kbars
                return []

        # Merge cached + broker data, sorted by timestamp
        all_kbars = cached_kbars + broker_kbars
        all_kbars.sort(key=lambda k: k.timestamp)

        # Remove duplicates (keep first occurrence)
        seen_timestamps = set()
        unique_kbars = []
        for kb in all_kbars:
            ts = kb.timestamp
            if ts not in seen_timestamps:
                unique_kbars.append(kb)
                seen_timestamps.add(ts)

        print(f"[kbars] Returning {len(unique_kbars)} total kbars for {symbol}")
        return unique_kbars

    def _calculate_kbar_index(self, symbol: str, mock_time: datetime) -> int:
        """Return the row-index of the latest kbar whose timestamp <= mock_time.

        Uses binary search (numpy.searchsorted) on the pre-built timestamps array
        so the result is always aligned to real kbar timestamps rather than an
        assumed-uniform minute grid.  This prevents drift when:
          - A trading day has fewer than the expected 270 1-min bars (common with
            real-broker data or yfinance gaps).
          - adjust_time() jumps across multiple days at once.

        Returns -1 when no data is available for the symbol.
        """
        import numpy as np

        if symbol not in self.market.historical_data:
            return -1

        info = self.market.historical_data[symbol]
        timestamps = info.get("timestamps")
        if timestamps is None or len(timestamps) == 0:
            return -1

        # Normalise both sides to datetime64[ns] (timezone-naive, UTC+8 wall clock)
        # – timestamps from pandas DataFrame index are already naive UTC+8
        # – mock_time is also naive UTC+8 (produced by ArenaX_Market)
        target = np.datetime64(mock_time.replace(tzinfo=None), 'ns')
        ts_arr = timestamps.astype('datetime64[ns]')

        # side='right': first index where ts > target, minus 1 → last bar with ts <= target
        idx = int(np.searchsorted(ts_arr, target, side='right')) - 1
        return max(0, min(idx, len(timestamps) - 1))

    def snapshot(self, symbol: str) -> Snapshot:
        if not hasattr(self, "market"):
            return self._create_fallback_snapshot(symbol, datetime.now())
        self._check_if_any_order_filled()

        if symbol not in self.market.historical_data:
            if self.real_account and not self.real_account.is_connected():
                self.real_account.connect()

            day_preload = self.num_days_preload if self.real_account else 5
            self.market.create_historical_market(symbol, day_preload)

        mock_current_time = self.market.get_market_time()["mock_current_time"]
        adjusted_mock_time = self.market.adjust_to_market_hours(mock_current_time)

        if symbol in self.market.historical_data:
            data_info = self.market.historical_data[symbol]
            data = data_info["data"]
            timestamps = data_info["timestamps"]

            if not data.empty and timestamps is not None:
                data_idx = self._calculate_kbar_index(symbol, adjusted_mock_time)
                daily_data = data.iloc[: data_idx + 1]

                if len(daily_data) > 0:
                    daily_open = daily_data["Open"].iloc[0].item()
                    daily_close = daily_data["Close"].iloc[-1].item()
                    daily_high = daily_data["High"].max().item()
                    daily_low = daily_data["Low"].min().item()
                    current_volume = daily_data["Volume"].iloc[-1].item()

                    current_price = round(daily_close, 2)
                    daily_open = round(daily_open, 2)
                    daily_high = round(daily_high, 2)
                    daily_low = round(daily_low, 2)

                    snap = Snapshot(
                        symbol=symbol,
                        exchange="TSE",
                        timestamp=adjusted_mock_time,
                        open=daily_open,
                        close=current_price,
                        high=daily_high,
                        low=daily_low,
                        volume=int(current_volume),
                        average_price=round((daily_high + daily_low) / 2, 2),
                        action=OrderAction.BUY if current_price >= daily_open else OrderAction.SELL,
                        buy_price=current_price,
                        buy_volume=int(current_volume // 10),
                        sell_price=round(current_price + 0.5, 2),
                        sell_volume=int(current_volume // 10),
                    )
                    return snap

        return self._create_fallback_snapshot(symbol, adjusted_mock_time)

    # corresponding command in cjtrade shell: lsodr
    def list_trades(self) -> List[Trade]:
        self._check_if_any_order_filled()

        trades = []
        all_orders = (
            self.account_state.orders_placed
            + self.account_state.orders_committed
            + self.account_state.orders_filled
            + self.account_state.orders_cancelled
        )
        for order in all_orders:
            trades.append(
                Trade(
                    id=order.id,
                    symbol=order.product.symbol,
                    action=order.action.value,
                    quantity=order.quantity,
                    price=order.price,
                    status=self.account_state.all_order_status.get(order.id, OrderStatus.UNKNOWN).value,
                    order_type=order.order_type.value,
                    price_type=order.price_type.value,
                    order_lot=order.order_lot,
                    order_datetime=order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    deals=0,
                    ordno=order.id,
                )
            )
        return trades

    def place_order(self, order: Order) -> OrderResult:
        if not self._is_valid_price(order):
            return REJECTED_ORDER_NEGATIVE_PRICE(order, metadata=order.opt_field)
        if not self._is_valid_quantity(order):
            return REJECTED_ORDER_NEGATIVE_QUANTITY(order, metadata=order.opt_field)

        if not self._is_within_trading_limit(order):
            return REJECTED_ORDER_EXCEED_TRADING_LIMIT(order, metadata=order.opt_field)

        if order.action == OrderAction.BUY:
            if not self._is_sufficient_account_balance(order):
                return REJECTED_ORDER_NOT_SUFFICIENT_BALANCE(order, metadata=order.opt_field)
        elif order.action == OrderAction.SELL:
            if not self._is_sufficient_account_inventory(order):
                return REJECTED_ORDER_NOT_SUFFICIENT_STOCK(order, metadata=order.opt_field)

        if hasattr(self, "market"):
            order.opt_field["last_check_for_fill"] = self.market.get_market_time()["mock_current_time"]
        else:
            order.opt_field["last_check_for_fill"] = datetime.now()

        self.account_state.orders_placed.append(order)
        self.account_state.all_order_status[order.id] = OrderStatus.PLACED
        return PLACED_ORDER_STANDARD(order, metadata=order.opt_field)

    def commit_order(self, order_id: str) -> OrderResult:
        order = next((o for o in self.account_state.orders_placed if o.id == order_id), None)
        if not order:
            return REJECTED_ORDER_NOT_FOUND_FOR_COMMIT(order_id)

        self.account_state.orders_committed.append(order)
        self.account_state.orders_placed.remove(order)

        market_open = hasattr(self, "market") and self.market.is_market_open()
        if market_open:
            self.account_state.all_order_status[order.id] = OrderStatus.COMMITTED_WAIT_MATCHING
            status = OrderStatus.COMMITTED_WAIT_MATCHING
        else:
            self.account_state.all_order_status[order.id] = OrderStatus.COMMITTED_WAIT_MARKET_OPEN
            status = OrderStatus.COMMITTED_WAIT_MARKET_OPEN

        self._check_if_any_order_filled()  # workaround

        return OrderResult(
            status=status,
            message="Order committed successfully." if market_open else "Order pending market open.",
            metadata={"market_open": market_open},
            linked_order=order.id,
        )

    def cancel_order(self, order_id: str) -> OrderResult:
        order_to_cancel = None
        source_list = None

        for order in self.account_state.orders_placed:
            if order.id == order_id:
                order_to_cancel = order
                source_list = self.account_state.orders_placed
                break

        if not order_to_cancel:
            for order in self.account_state.orders_committed:
                if order.id == order_id:
                    order_to_cancel = order
                    source_list = self.account_state.orders_committed
                    break

        if not order_to_cancel:
            for order in self.account_state.orders_filled:
                if order.id == order_id:
                    return REJECTED_ORDER_HAS_BEEN_FILLED(order)

        if not order_to_cancel:
            return REJECTED_ORDER_NOT_FOUND_FOR_CANCEL(order_id)

        source_list.remove(order_to_cancel)
        self.account_state.orders_cancelled.append(order_to_cancel)
        self.account_state.all_order_status[order_id] = OrderStatus.CANCELLED
        return CANCELLED_ORDER_STANDARD(order_to_cancel)


#############################  Internal Function (start)  #############################
    def _sync_with_real_account(self) -> None:
        """Sync position structure from real account (legacy-compatible)."""
        if not self.real_account:
            return

        try:
            if not self.real_account.is_connected():
                self.real_account.connect()
            print("Syncing with real account...")

            self.account_state.balance = self.real_account.get_balance()
            real_positions = self.real_account.get_positions()

            if not real_positions:
                print("No positions in real account")
                self.account_state.positions = []
                return

            day_preload = self.num_days_preload if self.real_account else 5
            # print(f"preload: {day_preload}")
            for pos in real_positions:
                if (
                    not self.skip_data_preload
                    and hasattr(self, "market")
                    and pos.symbol not in getattr(self.market, "historical_data", {})
                    and hasattr(self.market, "create_historical_market")
                ):
                    self.market.create_historical_market(pos.symbol, day_preload)

                self.account_state.fill_history.append({
                    "id": f"init_{pos.symbol}_{int(datetime.now().timestamp())}",
                    "order_id": "manual_sync",
                    "symbol": pos.symbol,
                    "action": "BUY",
                    "quantity": pos.quantity,
                    "price": pos.avg_cost,
                    "time": "initial_sync",
                })

            if not self.skip_data_preload:
                self._update_position_prices()
        except Exception as exc:
            print(f"Error syncing with real account: {exc}")

    def _sync_with_mock_account_file(self) -> None:
        """Load account state from JSON file and update prices from simulation."""
        import json

        if not os.path.exists(self.account_state_default_file):
            default_data = {
                "balance": 100_000.0,
                "positions": [],
                "orders_placed": [],
                "orders_committed": [],
                "orders_filled": [],
                "orders_cancelled": [],
                "all_order_status": {},
                "fill_history": [],
            }
            with open(self.account_state_default_file, "w") as f:
                json.dump(default_data, f, indent=4)

        with open(self.account_state_default_file, "r") as f:
            data = json.load(f)
            self.account_state.balance = data.get("balance", 100_000.0)
            self.account_state.fill_history = data.get("fill_history", [])

            self._reconstruct_positions_from_history()

            if self.account_state.positions:
                for pos in self.account_state.positions:
                    if (
                        not self.skip_data_preload
                        and hasattr(self, "market")
                        and pos.symbol not in getattr(self.market, "historical_data", {})
                        and hasattr(self.market, "create_historical_market")
                    ):
                        self.market.create_historical_market(pos.symbol, self.num_days_preload)

            self.account_state.orders_placed = [
                self._deserialize_order(order_data)
                for order_data in data.get("orders_placed", [])
            ]
            self.account_state.orders_committed = [
                self._deserialize_order(order_data)
                for order_data in data.get("orders_committed", [])
            ]
            self.account_state.orders_filled = [
                self._deserialize_order(order_data)
                for order_data in data.get("orders_filled", [])
            ]
            self.account_state.orders_cancelled = [
                self._deserialize_order(order_data)
                for order_data in data.get("orders_cancelled", [])
            ]

            self.account_state.all_order_status = {}
            for order_id, status in data.get("all_order_status", {}).items():
                try:
                    self.account_state.all_order_status[order_id] = OrderStatus(status)
                except Exception:
                    self.account_state.all_order_status[order_id] = OrderStatus.UNKNOWN

            now = datetime.now()
            self.account_state.orders_cancelled = [
                order for order in self.account_state.orders_cancelled
                if (now - order.created_at).total_seconds() < 1800
            ]

        if self.account_state.positions and not self.skip_data_preload:
            self._update_position_prices()

    def _deserialize_order(self, order_data: Dict) -> Order:
        order_lot_value = order_data.get("order_lot")
        if isinstance(order_lot_value, bool):
            order_lot = OrderLot.IntraDayOdd if order_lot_value else OrderLot.Common
        else:
            order_lot = OrderLot(order_lot_value)

        created_at = order_data.get("created_at")
        if created_at:
            created_time = datetime.fromisoformat(created_at)
        else:
            created_time = datetime.now()

        return Order(
            id=order_data.get("id", ""),
            product=Product(
                symbol=order_data.get("symbol", ""),
                type=ProductType.STOCK,
                exchange=Exchange.TSE,
            ),
            action=OrderAction(order_data.get("action", "BUY")),
            price=order_data.get("price", 0),
            quantity=order_data.get("quantity", 0),
            price_type=PriceType(order_data.get("price_type", "LMT")),
            order_type=OrderType(order_data.get("order_type", "ROD")),
            order_lot=order_lot,
            created_at=created_time,
        )

    def _serialize_state_to_json(self):
        data = {
            "balance": self.account_state.balance,
            "positions": [
                {
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "avg_cost": pos.avg_cost,
                    "current_price": pos.current_price,
                    "market_value": pos.market_value,
                    "unrealized_pnl": pos.unrealized_pnl
                } for pos in self.account_state.positions
            ],
            "orders_placed": [
                {
                    "id": order.id,
                    "symbol": order.product.symbol,
                    "action": order.action.value,
                    "price": order.price,
                    "quantity": order.quantity,
                    "price_type": order.price_type.value,
                    "order_type": order.order_type.value,
                    "order_lot": order.order_lot,
                    "created_at": order.created_at.isoformat()
                } for order in self.account_state.orders_placed
            ],
            "orders_committed": [
                {
                    "id": order.id,
                    "symbol": order.product.symbol,
                    "action": order.action.value,
                    "price": order.price,
                    "quantity": order.quantity,
                    "price_type": order.price_type.value,
                    "order_type": order.order_type.value,
                    "order_lot": order.order_lot,
                    "created_at": order.created_at.isoformat()
                } for order in self.account_state.orders_committed
            ],
            "orders_filled": [
                {
                    "id": order.id,
                    "symbol": order.product.symbol,
                    "action": order.action.value,
                    "price": order.price,
                    "quantity": order.quantity,
                    "price_type": order.price_type.value,
                    "order_type": order.order_type.value,
                    "order_lot": order.order_lot,
                    "created_at": order.created_at.isoformat()
                } for order in self.account_state.orders_filled
            ],
            "orders_cancelled": [
                {
                    "id": order.id,
                    "symbol": order.product.symbol,
                    "action": order.action.value,
                    "price": order.price,
                    "quantity": order.quantity,
                    "price_type": order.price_type.value,
                    "order_type": order.order_type.value,
                    "order_lot": order.order_lot,
                    "created_at": order.created_at.isoformat()
                } for order in self.account_state.orders_cancelled
            ],
            "all_order_status": {
                order_id: status.value
                for order_id, status in self.account_state.all_order_status.items()
            },
            "fill_history": self.account_state.fill_history
        }
        return data

    def _is_sufficient_account_balance(self, order: Order) -> bool:
        required_amount = order.price * order.quantity
        return self.account_state.balance >= required_amount

    def _is_sufficient_account_inventory(self, order: Order) -> bool:
        position = next((pos for pos in self.account_state.positions if pos.symbol == order.product.symbol), None)
        return bool(position and position.quantity >= order.quantity)

    def _is_valid_price(self, order: Order) -> bool:
        return order.price > 0

    def _is_valid_quantity(self, order: Order) -> bool:
        return order.quantity > 0

    def _is_within_trading_limit(self, order: Order) -> bool:
        trade_limit = 1_000_000.0
        if not hasattr(self, "market"):
            return True

        trades = self.list_trades()
        today_str = self.market.get_market_time()["mock_current_time"].strftime("%Y-%m-%d")
        traded_sum = 0.0
        for trade in trades:
            if trade.status in [
                OrderStatus.COMMITTED_WAIT_MATCHING.value,
                OrderStatus.FILLED.value,
            ] and trade.order_datetime.startswith(today_str):
                traded_sum += trade.price * trade.quantity
        return traded_sum + (order.price * order.quantity) <= trade_limit

    def _check_if_any_order_filled(self) -> bool:
        if not hasattr(self, "market"):
            return False
        # print("Checking for order fills...")

        committed_copy = list(self.account_state.orders_committed)
        for order in committed_copy:
            target_price = order.price
            cmp_time_range_start = order.opt_field.get(
                "last_check_for_fill",
                self.market.get_market_time()["mock_init_time"],
            )
            cmp_time_range_end = self.market.get_market_time()["mock_current_time"]

            # print(f"Checking order {order.id} from {cmp_time_range_start} to {cmp_time_range_end} against target price {target_price} !!!")

            if cmp_time_range_end <= cmp_time_range_start:
                continue

            price_filled = False
            if order.action == OrderAction.BUY:
                price_filled = self._check_price_in_time_range(
                    order.product.symbol,
                    cmp_time_range_start,
                    cmp_time_range_end,
                    lambda p: p <= target_price,
                )
            elif order.action == OrderAction.SELL:
                price_filled = self._check_price_in_time_range(
                    order.product.symbol,
                    cmp_time_range_start,
                    cmp_time_range_end,
                    lambda p: p >= target_price,
                )

            order.opt_field["last_check_for_fill"] = cmp_time_range_end

            if price_filled and price_filled > 0:
                try:
                    self.account_state.orders_filled.append(order)
                    if order in self.account_state.orders_committed:
                        self.account_state.orders_committed.remove(order)
                    self.account_state.all_order_status[order.id] = OrderStatus.FILLED

                    fill_time = self.market.start_date + timedelta(minutes=price_filled)
                    qty_signed = order.quantity if order.action == OrderAction.BUY else -order.quantity
                    self.account_state.balance -= (qty_signed * order.price)

                    self.account_state.fill_history.append({
                        "id": f"fill_{order.id}_{int(datetime.now().timestamp())}",
                        "order_id": order.id,
                        "symbol": order.product.symbol,
                        "action": order.action.value,
                        "quantity": qty_signed,
                        "price": order.price,
                        "time": fill_time.isoformat(),
                        # Propagate session_id from the order so the client can
                        # filter fill_history by session after the backtest ends.
                        "session_id": order.opt_field.get("session_id") if order.opt_field else None,
                    })
                    print("Order filled:", order.id)

                    self._reconstruct_positions_from_history()
                except Exception as exc:
                    print(f"Error moving order {order.id} to filled: {exc}")
        return True

    def _check_price_in_time_range(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        price_condition,
    ) -> int:
        try:
            if symbol not in self.market.historical_data:
                return False

            data_info = self.market.historical_data[symbol]
            data = data_info.get("data")
            timestamps = data_info.get("timestamps")

            if data is None or data.empty or timestamps is None:
                return False

            start_offset = int((start_time - self.market.start_date).total_seconds() / 60)
            end_offset = int((end_time - self.market.start_date).total_seconds() / 60)
            if end_offset <= start_offset:
                return False

            n = len(data)
            if n == 0:
                return False

            for minute in range(start_offset + 1, end_offset + 1):
                idx = minute % n
                try:
                    try:
                        close_price = float(data["Close"].iat[idx])
                    except Exception:
                        close_price = float(data["Close"].iloc[idx].item())
                except Exception:
                    try:
                        close_price = float(data.iloc[idx]["Close"])
                    except Exception:
                        try:
                            close_price = float(data.iloc[idx]["close"])
                        except Exception:
                            continue

                if price_condition(close_price):
                    return minute
            return -1
        except Exception as exc:
            print(f"_check_price_in_time_range error: {exc}")
            return -1

    def _reconstruct_positions_from_history(self) -> None:
        if not self.account_state.fill_history:
            self.account_state.positions = []
            return

        from collections import defaultdict

        sym_fills = defaultdict(list)
        for fill in self.account_state.fill_history:
            sym_fills[fill["symbol"]].append(fill)

        new_positions = []
        for sym, fills in sym_fills.items():
            net_qty = 0
            total_buy_cost = 0.0
            total_buy_qty = 0

            for fill in fills:
                q = fill["quantity"]
                p = fill["price"]

                if q > 0:
                    total_buy_cost += (q * p)
                    total_buy_qty += q
                    net_qty += q
                else:
                    net_qty += q

            if net_qty == 0:
                continue

            avg_cost = total_buy_cost / total_buy_qty if total_buy_qty > 0 else 0.0
            new_positions.append(Position(
                symbol=sym,
                quantity=net_qty,
                avg_cost=round(avg_cost, 2),
                current_price=round(avg_cost, 2),
                market_value=round(net_qty * avg_cost, 1),
                unrealized_pnl=0.0,
            ))

        self.account_state.positions = new_positions

    def _update_position_prices(self) -> None:
        if not self.account_state.positions:
            return
        if not hasattr(self, "snapshot"):
            return

        updated_positions = []
        for pos in self.account_state.positions:
            try:
                snapshot = self.snapshot(pos.symbol)
                simulated_price = round(snapshot.close, 2)
                updated_positions.append(Position(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    avg_cost=round(pos.avg_cost, 2),
                    current_price=simulated_price,
                    market_value=round(pos.quantity * simulated_price, 1),
                    unrealized_pnl=round((simulated_price - pos.avg_cost) * pos.quantity, 1),
                ))
            except Exception as exc:
                print(f"Warning: Failed to update price for {pos.symbol}: {exc}")
                updated_positions.append(pos)

        self.account_state.positions = updated_positions

    def _create_fallback_snapshot(self, symbol: str, timestamp: datetime) -> Snapshot:
        import random

        base_price = 100.0 + random.uniform(-10, 10)
        price_change = random.uniform(-2, 2)

        return Snapshot(
            symbol=symbol,
            exchange="TSE",
            timestamp=timestamp,
            open=base_price,
            close=base_price + price_change,
            high=base_price + abs(price_change) + random.uniform(0, 1),
            low=base_price - abs(price_change) - random.uniform(0, 1),
            volume=random.randint(1000, 100000),
            average_price=base_price + price_change / 2,
            action=OrderAction.BUY if price_change >= 0 else OrderAction.SELL,
            buy_price=base_price + price_change,
            buy_volume=random.randint(500, 50000),
            sell_price=base_price + price_change + 0.5,
            sell_volume=random.randint(500, 50000),
        )

    def _aggregate_kbars_internal(self, kbars: List[Kbar], target_interval: str) -> List[Kbar]:
        if not kbars:
            return []

        interval_minutes = {
            "3m": 3,
            "6m": 6,
            "12m": 12,
            "20m": 20,
            "45m": 45,
        }

        if target_interval not in interval_minutes:
            raise ValueError(f"Mock broker: Unsupported interval for aggregation: {target_interval}")

        target_mins = interval_minutes[target_interval]
        data = {
            "timestamp": [k.timestamp for k in kbars],
            "open": [k.open for k in kbars],
            "high": [k.high for k in kbars],
            "low": [k.low for k in kbars],
            "close": [k.close for k in kbars],
            "volume": [k.volume for k in kbars],
        }
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)

        freq = f"{target_mins}min"
        aggregated = df.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        result = []
        for timestamp, row in aggregated.iterrows():
            kbar = Kbar(
                timestamp=timestamp.to_pydatetime(),
                open=round(row["open"], 2),
                high=round(row["high"], 2),
                low=round(row["low"], 2),
                close=round(row["close"], 2),
                volume=int(row["volume"]),
            )
            result.append(kbar)

        return result
#############################  Internal Function (end)  #############################
