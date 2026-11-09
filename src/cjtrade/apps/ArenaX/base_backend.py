import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict
from typing import List
from typing import Optional

import numpy as np
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
from cjtrade.apps.ArenaX.time_in_force import policy_for
from cjtrade.apps.ArenaX.time_in_force import TIFContext
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs import paths
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.cost import CostModel
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

# backtest / paper / demo
# mode = price_data_src + use_case
# backtest: (real_account + playback_speed + state_file + num_days_preload) + start/stop
# paper: (real_account + state_file) + start/stop
# demo: (playback_speed + state_file + num_days_preload) + start/stop
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


# Starting cash when no snapshot is resumed and the caller passed no
# initial_balance. Only a last resort: the launch form's "Initial Fund" is
# plumbed through as initial_balance and wins over this.
DEFAULT_INITIAL_BALANCE = 100_000.0


class ArenaX_BackendBase:
    def __init__(
        self,
        state_file: Optional[str] = None,
        state_dir: Optional[str] = None,
        session_id: Optional[str] = None,
        seed_from_live: bool = False,
        real_account: Optional[AccountClient] = None,
        playback_speed: float = 1.0,
        num_days_preload: int = 3,
        skip_data_preload: bool = False,
        initial_balance: float = 0.0,
        price_db_path: Optional[str] = None,
        cost_model: Optional[CostModel] = None,
        **kwargs,
    ) -> None:
        # ── Account state: snapshots in, a new snapshot out ───────────────────
        # state_file is the snapshot to RESUME FROM, and None (the default) means
        # a fresh account. It used to be a fixed path that login() read and
        # logout() overwrote, which made every run start where the previous one
        # ended -- so the same backtest produced different numbers each time,
        # silently.
        #
        # Output always goes to a new uuid-named file and never touches
        # state_in, so a snapshot you resumed from stays reusable and two runs
        # from the same snapshot are comparable.
        #
        # Identical for backtest / paper / demo / real: which mode you are in
        # does not change whether state should carry over.
        self.state_in = state_file or None
        self.session_id = session_id or uuid.uuid4().hex
        # Resolved here, not as a default argument: paths.* creates the
        # directory, and a default argument would do that at import time.
        self.state_dir = str(state_dir) if state_dir else str(paths.account_states_dir())
        self.state_out = os.path.join(self.state_dir, f"{self.session_id}.json")
        # Reading the live account is a deliberate, non-reproducible choice, so
        # it has to be asked for. It used to happen whenever the state file
        # merely did not exist yet.
        self.seed_from_live = seed_from_live
        self.real_account = real_account
        if self.real_account and not self.real_account.is_connected():
            self.real_account.connect()  # Early connection for fetching data
        self.playback_speed = playback_speed
        self.num_days_preload = num_days_preload
        self.skip_data_preload = skip_data_preload
        self._connected = False
        self._initial_balance_override = initial_balance  # stored for use in login()
        self.account_state = ArenaX_AccountState()
        self.price_db_path = str(price_db_path) if price_db_path else str(paths.price_db_path())
        self._cost_model = cost_model if cost_model is not None else CostModel()

    # NOTE: login() affect whether the account state is synced and whether the flag _connected is set.
    def login(self) -> bool:
        try:
            self._connected = True

            if self.state_in:
                print(f"[state] resuming from snapshot: {self.state_in}")
                self._load_state_from(self.state_in)
            elif self.seed_from_live and self.real_account:
                print("[state] seeding from live account — this run is NOT reproducible")
                self._sync_with_real_account()
            else:
                print("[state] fresh account")
                self._init_fresh_state()
            print(f"[state] session {self.session_id} — "
                  f"snapshot will be written to {self.state_out}")

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
        self._write_state_snapshot()
        self._connected = False
        print("Simulation environment stopped")

    def _write_state_snapshot(self) -> None:
        """Persist the final state to this session's own file.

        Never writes back to state_in: a snapshot is immutable once produced, so
        resuming from it twice gives the same starting point both times. The
        metadata records where this run came from, which gives the snapshots a
        traceable lineage.
        """
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            data = self._serialize_state_to_json()
            data["_meta"] = {
                "session_id": self.session_id,
                "parent_session": self.state_in,
                "created_at": datetime.now().isoformat(),
                "backend": type(self).__name__,
                "initial_balance": self.account_state.initial_balance,
                "seeded_from_live": bool(self.seed_from_live and self.real_account),
            }
            with open(self.state_out, "w") as f:
                json.dump(data, f, indent=4)
            print(f"[state] snapshot written: {self.state_out}")
        except Exception as exc:
            print(f"[state] failed to write snapshot {self.state_out}: {exc}")

    def _init_fresh_state(self) -> None:
        """Start from an empty account. Touches no disk.

        Uses the caller's initial_balance when given, so the number the user
        typed into the launch form is the number the run actually starts with.
        """
        self.account_state.balance = (
            self._initial_balance_override
            if self._initial_balance_override > 0
            else DEFAULT_INITIAL_BALANCE
        )
        self.account_state.positions = []
        self.account_state.orders_placed = []
        self.account_state.orders_committed = []
        self.account_state.orders_filled = []
        self.account_state.orders_cancelled = []
        self.account_state.all_order_status = {}
        self.account_state.fill_history = []

    def is_connected(self) -> bool:
        return self._connected

    def account_balance(self) -> float:
        return self.account_state.balance

    def list_positions(self) -> List[Position]:
        self._reconstruct_positions_from_history()
        self._update_position_prices()
        return self.account_state.positions

    # TODO: Also store to local 1d kbar price cache
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
                    symbol=symbol,
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
        # Shioaji (sinopac) fetches 1-minute data internally and aggregates, so it has a
        # hard 30-day limit per request.  Split every missing range into ≤30-day chunks.
        _BROKER_MAX_DAYS = 30
        broker_kbars = []
        if missing_ranges and self.real_account:
            try:
                from datetime import timedelta as _td
                chunked_ranges = []
                for start_epoch, end_epoch in missing_ranges:
                    chunk_start = dt.fromtimestamp(start_epoch)
                    chunk_end   = dt.fromtimestamp(end_epoch)
                    while chunk_start < chunk_end:
                        chunk_stop = min(chunk_start + _td(days=_BROKER_MAX_DAYS), chunk_end)
                        chunked_ranges.append((chunk_start, chunk_stop))
                        chunk_start = chunk_stop

                for chunk_start_dt, chunk_end_dt in chunked_ranges:
                    range_start = chunk_start_dt.strftime("%Y-%m-%d")
                    range_end   = chunk_end_dt.strftime("%Y-%m-%d")
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
                                start_ts=chunk_start_dt,
                                end_ts=chunk_end_dt,
                                source="broker_api"
                            )
                        except Exception as e:
                            print(f"[kbars] Error caching fetched data: {e}")

            except Exception as exc:
                print(f"[kbars] Error fetching from broker for {symbol}: {exc}")
                # Do NOT return here — fall through to the yfinance fallback below.
                if cached_kbars:
                    return cached_kbars

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

        # Final fallback: yfinance (covers demo mode and any other case where
        # neither price_db nor real_account yielded results)
        if not unique_kbars:
            print(f"[kbars] No data from price_db/broker for {symbol}, falling back to yfinance")
            unique_kbars = self.kbars_yf(symbol, start, end, interval)

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

                # Aggregate only the day the latest bar belongs to. This used
                # to slice from row 0 of the whole preloaded range, so `open`
                # was the first bar of the entire backtest and `high`/`low`
                # were the running extremes across every day loaded -- numbers
                # that drifted further from the truth the longer a replay ran,
                # while being named `daily_*`. Only `close` was ever right.
                #
                # Keyed on the latest bar's own day rather than on
                # adjusted_mock_time's: asked for a moment before the first bar
                # of a session (the data starts at 09:01, not 09:00) this
                # reports the previous session's figures, which is what a
                # pre-open snapshot should say. Keying on the requested day
                # would slice to nothing and fall through to the random
                # fallback snapshot below.
                day_start = int(data.index.searchsorted(
                    data.index[data_idx].normalize()
                ))
                daily_data = data.iloc[day_start:data_idx + 1]

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
        # Fill check first, then expiry -- the same order place_order uses, and
        # it matters. Expiring first would discard a legitimate fill sitting in
        # the not-yet-checked window *before* the deadline: a clock that jumps
        # 13:24 -> next 09:00 leaves 13:25-13:30 unexamined, and those bars can
        # still fill a ROD order.
        #
        # The expiry sweep belongs here because this is the per-bar path. The
        # engine polls resting orders through list_orders() every bar, and that
        # path used to run the matcher with no time-in-force behind it, so the
        # only thing that ever expired an order was the server's wall-clock
        # matching loop -- which races the replay instead of following it.
        self._check_if_any_order_filled()
        self.expire_resting_orders()

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

        # Commit immediately: skip the PLACED staging area entirely.
        # PLACED is an ArenaX server-side implementation detail; callers should
        # never see it as an intermediate state.
        market_open = hasattr(self, "market") and self.market.is_market_open()
        initial_status = OrderStatus.COMMITTED_WAIT_MATCHING if market_open else OrderStatus.COMMITTED_WAIT_MARKET_OPEN
        self.account_state.orders_committed.append(order)
        self.account_state.all_order_status[order.id] = initial_status

        # Attempt an immediate fill check (common in backtest with fast playback).
        self._check_if_any_order_filled()
        # Then let the order's time-in-force have its say. This is what makes
        # IOC and FOK real: the fill check above was their one chance.
        self.expire_resting_orders()

        # Return the actual status after the fill check (may have advanced to FILLED).
        actual_status = self.account_state.all_order_status.get(order.id, initial_status)
        return OrderResult(
            status=actual_status,
            message="Order filled." if actual_status == OrderStatus.FILLED else (
                "Order committed, waiting for match." if market_open else "Order committed, waiting for market open."
            ),
            metadata=order.opt_field or {},
            linked_order=order.id,
        )

    def sync_state(self, order_id: str) -> OrderResult:
        """Refresh the status of a committed order by re-running the fill check.

        Pure read/refresh operation — no state transitions performed here.
        Returns the current status from all_order_status.
        """
        # Check if already resolved (filled / cancelled)
        current_status = self.account_state.all_order_status.get(order_id)
        if current_status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return OrderResult(
                status=current_status,
                message="Order already resolved.",
                metadata={},
                linked_order=order_id,
            )

        order = next((o for o in self.account_state.orders_committed if o.id == order_id), None)
        if not order:
            return REJECTED_ORDER_NOT_FOUND_FOR_COMMIT(order_id)

        self._check_if_any_order_filled()

        actual_status = self.account_state.all_order_status.get(order_id, OrderStatus.COMMITTED_WAIT_MATCHING)
        return OrderResult(
            status=actual_status,
            message="Order state refreshed.",
            metadata={},
            linked_order=order_id,
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

    def _load_state_from(self, path: str) -> None:
        """Resume from an existing snapshot. Read-only: never writes `path`.

        Does not create the file when missing. A requested snapshot that is not
        there is a caller mistake worth surfacing, not something to paper over
        with defaults -- the run would otherwise start from a balance nobody
        asked for and still look successful.
        """
        import json

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"account state snapshot not found: {path}. "
                f"Omit it to start from a fresh account."
            )

        with open(path, "r") as f:
            data = json.load(f)
            self.account_state.balance = data.get("balance", DEFAULT_INITIAL_BALANCE)
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

    def expire_resting_orders(self, now: Optional[datetime] = None) -> List[str]:
        """Ask each resting order's time-in-force whether it should still live.

        Returns the ids cancelled. This is where EOD cancelling lives now: it
        used to be a date-latched sweep inside the HTTP server's matching loop
        (brokerside_server._cancel_eod_orders), which meant a backend used
        without a server had no expiry at all, and the sweep could not tell ROD
        from IOC.
        """
        if now is None:
            if not hasattr(self, "market"):
                return []
            now = self.market.get_market_time()["mock_current_time"]

        calendar = getattr(getattr(self, "market", None), "calendar", None) or TradingCalendar()
        ctx = TIFContext(now=now, calendar=calendar)

        cancelled = []
        for order in list(self._resting_orders()):
            decision = policy_for(order.order_type).on_no_fill(order, ctx)
            if not decision.cancel:
                continue
            try:
                # Through cancel_order so there is one cancellation path: it
                # moves the lists, sets the status, and therefore releases the
                # reservation in the same step.
                self.cancel_order(order.id)
                cancelled.append(order.id)
                print(f"[TIF] {order.order_type.value} {order.id} cancelled: "
                      f"{decision.reason}")
            except Exception as exc:
                print(f"[TIF] Could not cancel {order.id}: {exc}")
        return cancelled

    # ── Reservation ───────────────────────────────────────────────────────────
    # An accepted order encumbers what it will need until it fills or dies.
    # Derived from the order lists rather than a counter, so the reservation is
    # released by the same action that moves the real resource: a fill removes
    # the order from orders_committed and mutates balance/position together.

    def _resting_orders(self) -> List[Order]:
        """Orders the account has out with the exchange, nothing decided yet."""
        return (self.account_state.orders_placed
                + self.account_state.orders_committed)

    def _reserved_cash(self) -> float:
        """Cash committed by resting BUY orders (值 + 手續費)."""
        total = 0.0
        for o in self._resting_orders():
            if o.action == OrderAction.BUY:
                value = o.price * o.quantity
                total += value + self._cost_model.calc_commission(value)
        return total

    def _reserved_quantity(self, symbol: str) -> int:
        """Shares committed by resting SELL orders on `symbol`."""
        return sum(o.quantity for o in self._resting_orders()
                   if o.action == OrderAction.SELL
                   and o.product.symbol == symbol)

    def buying_power(self) -> float:
        return self.account_state.balance - self._reserved_cash()

    def available_to_sell(self, symbol: str) -> int:
        position = next((pos for pos in self.account_state.positions
                         if pos.symbol == symbol), None)
        held = position.quantity if position else 0
        return held - self._reserved_quantity(symbol)

    def _is_sufficient_account_balance(self, order: Order) -> bool:
        value = order.price * order.quantity
        commission = self._cost_model.calc_commission(value)
        required_amount = value + commission
        # Against buying power, not raw balance: balance only drops at fill
        # time, so N resting BUYs each used to "fit" inside the same cash and
        # the account went negative when they all filled.
        return self.buying_power() >= required_amount

    def _is_sufficient_account_inventory(self, order: Order) -> bool:
        # Against available-to-sell, not the whole position: a resting SELL did
        # not reduce it (positions come from fill_history), so the same shares
        # could be sold twice and fill_history went net-negative — a short
        # position in a cash equity account, reported without complaint.
        return self.available_to_sell(order.product.symbol) >= order.quantity

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
        # Every status that still consumes the day's quota. WAIT_MARKET_OPEN and
        # PLACED were missing, so orders stacked up before the open did not
        # count and the limit could be walked straight past.
        counted = {
            OrderStatus.PLACED.value,
            OrderStatus.COMMITTED_WAIT_MARKET_OPEN.value,
            OrderStatus.COMMITTED_WAIT_MATCHING.value,
            OrderStatus.PARTIAL.value,
            OrderStatus.FILLED.value,
        }
        traded_sum = 0.0
        for trade in trades:
            if trade.status in counted and trade.order_datetime.startswith(today_str):
                traded_sum += trade.price * trade.quantity
        return traded_sum + (order.price * order.quantity) <= trade_limit

    def _check_if_any_order_filled(self) -> bool:
        if not hasattr(self, "market"):
            return False
        # print("Checking for order fills...")

        calendar = getattr(self.market, "calendar", None) or TradingCalendar()

        committed_copy = list(self.account_state.orders_committed)
        for order in committed_copy:
            target_price = order.price
            cmp_time_range_start = order.opt_field.get(
                "last_check_for_fill",
                self.market.get_market_time()["mock_init_time"],
            )
            cmp_time_range_end = self.market.get_market_time()["mock_current_time"]

            # An order cannot fill after the moment its time-in-force ends it,
            # and the clock is free to jump straight over that moment: a replay
            # driver steps from the last bar of a session (13:24, say) to the
            # first bar of the next one, so nothing is ever asked about the
            # order while the clock sits past the close. Unclamped, the window
            # spans the overnight gap and a ROD order placed yesterday matches
            # today's opening bars -- verified: a 13:20 ROD filling at 09:01
            # the following day, 19 hours after its own expiry.
            deadline = policy_for(order.order_type).expires_at(order, calendar)
            if deadline is not None and deadline < cmp_time_range_end:
                cmp_time_range_end = deadline

            # print(f"Checking order {order.id} from {cmp_time_range_start} to {cmp_time_range_end} against target price {target_price} !!!")

            if cmp_time_range_end <= cmp_time_range_start:
                continue

            fill_time = self._find_fill_time(
                order.product.symbol,
                cmp_time_range_start,
                cmp_time_range_end,
                order.action,
                target_price,
            )

            order.opt_field["last_check_for_fill"] = cmp_time_range_end

            if fill_time is not None:
                self._apply_fill(order, order.price, fill_time)
        return True

    def _apply_fill(self, order: Order, fill_price: float,
                    fill_time: datetime) -> bool:
        """Book a fill: move the order, pay the costs, record it, re-derive positions.

        The only place any backend settles a fill. There used to be three
        copies — base, paper and real — and only this one applied the
        CostModel, so the same strategy paid commission and tax in backtest and
        nothing in paper. paper also dropped session_id, which broke the
        client's per-session filtering of fill_history.
        """
        try:
            if order in self.account_state.orders_committed:
                self.account_state.orders_committed.remove(order)
            if order in self.account_state.orders_placed:
                self.account_state.orders_placed.remove(order)
            self.account_state.orders_filled.append(order)
            self.account_state.all_order_status[order.id] = OrderStatus.FILLED

            value = fill_price * order.quantity
            commission = self._cost_model.calc_commission(value)
            tax = self._cost_model.calc_tax(value, order.action.value,
                                            order.product.symbol)
            if order.action == OrderAction.BUY:
                self.account_state.balance -= (value + commission)
            else:
                self.account_state.balance += (value - commission - tax)

            self.account_state.fill_history.append({
                "id": f"fill_{order.id}_{int(datetime.now().timestamp())}",
                "order_id": order.id,
                "symbol": order.product.symbol,
                "action": order.action.value,
                "quantity": order.quantity if order.action == OrderAction.BUY else -order.quantity,
                "price": fill_price,
                "commission": round(commission, 2),
                "tax": round(tax, 2),
                "time": fill_time.isoformat(),
                # Propagate session_id from the order so the client can
                # filter fill_history by session after the backtest ends.
                "session_id": order.opt_field.get("session_id") if order.opt_field else None,
            })
            print("Order filled:", order.id)

            self._reconstruct_positions_from_history()
            return True
        except Exception as exc:
            print(f"Error moving order {order.id} to filled: {exc}")
            return False

    def _find_fill_time(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        action: OrderAction,
        target_price: float,
    ) -> Optional[datetime]:
        """Timestamp of the first bar in (start_time, end_time] that would fill.

        A buy fills on the first close at or below its limit, a sell on the
        first close at or above it. Takes the action and the price rather than a
        predicate because a scalar predicate forces a Python loop: comparing
        the whole window at once is 16x faster over a one-day gap and 200x over
        a one-year one, and it keeps the cost flat enough that how long the
        clock jumped stops mattering.

        Searched by timestamp, the same way _calculate_kbar_index does it. An
        earlier version indexed bars on a uniform minute grid from start_date
        and wrapped with `idx = minute % n`: a trading day holds ~270 1m bars,
        not 1440, so the offset drifted a day further out every day and once it
        passed `n` the modulo silently matched an unrelated day's prices.

        Returns None when nothing matches — the fill timestamp itself is the
        answer, so the caller does not re-derive it from a minute offset.
        """
        try:
            data_info = self.market.historical_data.get(symbol)
            if not data_info:
                return None

            data = data_info.get("data")
            timestamps = data_info.get("timestamps")
            if data is None or data.empty or timestamps is None or len(timestamps) == 0:
                return None

            ts = pd.DatetimeIndex(timestamps)
            # (start, end]: start was already checked on the previous pass.
            lo = int(ts.searchsorted(pd.Timestamp(start_time), side="right"))
            hi = int(ts.searchsorted(pd.Timestamp(end_time), side="right"))
            if hi <= lo:
                return None

            column = "Close" if "Close" in data.columns else (
                "close" if "close" in data.columns else None
            )
            if column is None:
                print(f"_find_fill_time: no close column for {symbol} "
                      f"(have {list(data.columns)})")
                return None
            # Not cached: to_numpy() on a contiguous float column is ~5us even
            # for four years of 1m bars, so a cache would add an invalidation
            # story for no measurable gain.
            closes = data[column].to_numpy(dtype=float)
            window = closes[lo:min(hi, len(closes))]
            if window.size == 0:
                return None

            hits = (window <= target_price if action == OrderAction.BUY
                    else window >= target_price)
            if not hits.any():
                return None
            return ts[lo + int(np.argmax(hits))].to_pydatetime()
        except Exception as exc:
            # Report the type too: a bare message turned a NameError in here
            # into a silent "nothing filled", which looks exactly like a
            # correct no-match and cost an afternoon to spot.
            print(f"_find_fill_time error: {type(exc).__name__}: {exc}")
            return None

    def _reconstruct_positions_from_history(self) -> None:
        """Rebuild positions from fill_history, costing the shares still held.

        FIFO: a sell retires the oldest lots, so what remains in the queue IS
        the open position, and its cost is the cost of those lots alone.

        This used to average every buy the account had ever made and never let
        a sell reduce that average, so avg_cost drifted toward the mean traded
        price of the whole session instead of describing the open lot. Over 146
        buys and 145 sells it reported 247.50 for a position actually bought at
        243.00 -- and since unrealized_pnl is derived from avg_cost, every
        caller reading it (cjtrade_system's summary) was given a wrong number.
        market_value was unaffected, because _update_position_prices() re-marks
        it from a live snapshot.

        Fills are consumed in append order, not sorted: _sync_with_real_account
        seeds opening positions with time="initial_sync", which would sort after
        every real ISO timestamp and turn a pre-existing holding into the most
        recent buy.
        """
        if not self.account_state.fill_history:
            self.account_state.positions = []
            return

        from collections import defaultdict
        from collections import deque

        sym_fills = defaultdict(list)
        for fill in self.account_state.fill_history:
            sym_fills[fill["symbol"]].append(fill)

        new_positions = []
        for sym, fills in sym_fills.items():
            lots: deque = deque()   # [price, qty] per open lot, oldest first
            oversold = 0            # shares sold with no lot left to retire

            for fill in fills:
                # quantity is signed in fill_history: + for BUY, - for SELL
                # (see _apply_fill).
                qty = fill["quantity"]
                price = fill["price"]

                if qty > 0:
                    lots.append([price, qty])
                    continue

                remaining = -qty
                while remaining > 0 and lots:
                    lot_price, lot_qty = lots[0]
                    matched = min(remaining, lot_qty)
                    if matched >= lot_qty:
                        lots.popleft()
                    else:
                        lots[0][1] -= matched
                    remaining -= matched
                oversold += remaining

            held_qty = sum(q for _, q in lots) - oversold
            if held_qty == 0:
                continue

            if oversold:
                # Reservation should make this impossible (see _reserved_quantity
                # / available_to_sell). Report it rather than hiding it: a
                # negative share count in a cash equity account is a bug
                # upstream, and silently dropping the position would erase the
                # only evidence.
                print(f"Warning: {sym} fill history oversells by {oversold} "
                      f"share(s) — position reported as {held_qty}")

            held_cost = sum(p * q for p, q in lots)
            avg_cost = held_cost / held_qty if held_qty > 0 else 0.0
            new_positions.append(Position(
                symbol=sym,
                quantity=held_qty,
                avg_cost=round(avg_cost, 2),
                # Placeholders: _update_position_prices() overwrites both from a
                # live snapshot, and list_positions() always calls it next.
                current_price=round(avg_cost, 2),
                market_value=round(held_qty * avg_cost, 1),
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
        symbol = kbars[0].symbol        # aggregation never mixes symbols
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
                symbol=symbol,
            )
            result.append(kbar)

        return result
#############################  Internal Function (end)  #############################
