import os
from enum import Enum
from cjtrade.core.account_client import AccountClient
from cjtrade.models.position import Position
from cjtrade.models.product import Product
from cjtrade.models.quote import Snapshot
from cjtrade.models.order import Order, OrderAction, OrderResult, OrderStatus
from cjtrade.models.kbar import Kbar
from cjtrade.models.trade import Trade
from cjtrade.brokers.mock._mock_market import *
from cjtrade.brokers.mock._mock_broker_order_gen import *
from typing import Dict, List
import yfinance as yf
import datetime
import random
import pandas as pd

# Price generation modes for mock broker
class PriceMode(str, Enum):
    """Price generation strategy for mock broker.

    HISTORICAL: Replay historical market data from yfinance.
                Pros: Real market behavior, good for backtesting
                Cons: Limited to past 30 days of minute data

    SYNTHETIC: Generate random prices (future implementation).
               Pros: Can run indefinitely, customizable volatility
               Cons: Not realistic, can't verify strategy effectiveness
    """
    HISTORICAL = "historical"
    SYNTHETIC = "synthetic"  # TODO: Implement in future

# This is used to simulate a securities account
# It is for testing purposes, allowing users to test their trading strategies
# even if the market is closed or they don't have a real account.

# We need to keep track of some important variables and states, such as:
# - Account balance
# - Holdings
# - Open orders
# - Transaction history
# - Dynamic Market data (simulated by replaying historical data)

# If possible, we sync account data with real broker account data
# And only simulate the order execution and market data parts.

class MockBackend_AccountState:
    def __init__(self):
        self.positions: List[Position] = []
        self.balance: float = 0.0
        self.last_sync_time: str = ""           # Currently NOT used in any context
        self.orders_placed: List[Order] = []    # After `place_order()`
        self.orders_committed: List[Order] = [] # After `commit_order()`
        self.orders_filled: List[Order] = []        # Orders already filled
        self.orders_cancelled: List[Order] = []     # Orders already cancelled
        self.all_order_status: Dict[str, OrderStatus] = {}
        self.fill_history: List[Dict] = []         # Every transaction: {symbol, quantity, price, time}

# TODO: Consider to add exchange simulation when all time progression features are ready
# class MockBackend_StockExchange:
#     def __init__(self):
#         self.orders_filled: List[Order] = []        # Orders already filled


# Backend = Maintain Account State + Provide Market Data
# Note that the backend API scheme originates from Shioaji's design.
# TODO: Define data source spec to extract price input layer,
# to make it available for any kind of data (not only just calling `_create_historical_market`)
class MockBrokerBackend:
    def __init__(self, real_account: AccountClient = None, price_mode: PriceMode = PriceMode.HISTORICAL, playback_speed: float = 1.0, state_file: str = "mock_account_state.json"):
        self.real_account = real_account
        self.price_mode = price_mode
        self.account_state = MockBackend_AccountState()
        self.account_state_default_file = state_file

        # Initialize price engine based on mode
        if price_mode == PriceMode.HISTORICAL:
            self.market = MockBackend_MockMarket(real_account=self.real_account)
            self.market.set_historical_time(datetime.datetime.now(), days_back=random.randint(1, 20))
            self.market.set_playback_speed(playback_speed)
        else:
            # Future: self.market = MockBackend_SyntheticMarket()
            raise NotImplementedError(f"Price mode {price_mode} not yet implemented")

        self._connected = False

    ########################   Functions for mock_broker_api to call (start)   ########################
    def login(self) -> bool:
        try:
            self._connected = True

            if self.real_account:
                self._sync_with_real_account()
            else:
                self._sync_with_mock_account_file()

            print("Simulation environment started")
            return True
        except Exception as e:
            print(f"Failed to start simulation environment: {e}")
            self._connected = False
            return False

    def logout(self):
        if self.real_account:
            self.real_account.disconnect()
        with open(self.account_state_default_file, 'w') as f:
            import json
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
            json.dump(data, f, indent=4)
        self._connected = False
        print("Simulation environment stopped")

    def is_connected(self) -> bool:
        return self._connected

    def account_balance(self) -> float:
        return self.account_state.balance

    # TODO: Use same data from the MockBackend_MockMarket
    # TODO: Enable kbar aggregation for real account data source like what .snapshot() does
    # TODO: Move the market data generation logic to MockBackend_MockMarket
    # since kbars() right now are separate from the data used in snapshot()
    # it does not have time progression simulation
    def kbars(self, symbol: str, start: str, end: str, interval: str = "1m") -> List[Kbar]:
        yf_symbol = f"{symbol}.TW"

        try:
            # Download data from yfinance for the specified range
            data = yf.download(yf_symbol, start=start, end=end, interval=interval, auto_adjust=True, progress=False)

            if data.empty:
                print(f"No data available for {symbol} in range {start} to {end}")
                return []

            if not isinstance(data.index, pd.DatetimeIndex):
                data.index = pd.to_datetime(data.index)
            if data.index.tz is not None:
                # If yfinance data is UTC, need to convert to Taiwan time
                if str(data.index.tz) in ['UTC', 'UTC+00:00']:
                    import pytz
                    taiwan_tz = pytz.timezone('Asia/Taipei')
                    data.index = data.index.tz_convert(taiwan_tz).tz_localize(None)
                else:
                    data.index = data.index.tz_localize(None)

            kbars = []

            for timestamp, row in data.iterrows():
                kbar = Kbar(
                    timestamp=timestamp.to_pydatetime(),
                    open=round(row['Open'].item(), 2),
                    high=round(row['High'].item(), 2),
                    low=round(row['Low'].item(), 2),
                    close=round(row['Close'].item(), 2),
                    volume=int(row['Volume'].item())
                )
                kbars.append(kbar)

            # print(f"Loaded {len(kbars)} kbars for {symbol}")
            return kbars

        except Exception as e:
            print(f"Error loading kbars for {symbol}: {e}")
            return []

    # Note: snapshot() needs to simulate time progression
    # TODO: Move the market data generation logic to MockBackend_MockMarket
    def snapshot(self, symbol: str) -> Snapshot:
        self._check_if_any_order_filled()

        # Load data if not already loaded
        if symbol not in self.market.historical_data:
            if self.real_account and not self.real_account.is_connected():
                self.real_account.connect()

            # This will fetch from `real_account` or `yfinance`
            self.market.create_historical_market(symbol)

            if self.real_account:
                self.real_account.disconnect()

        time = self.market.get_market_time()
        real_current_time = time['real_current_time']
        time_offset = time['time_offset']
        mock_current_time = time['mock_current_time']

        # Adjust to market hours (freeze at 13:30 if after market close)
        adjusted_mock_time = self.market.adjust_to_market_hours(mock_current_time)

        # Calculate minutes passed in MOCK time (not real time)
        # This accounts for playback_speed
        mock_time_offset = adjusted_mock_time - self.market.start_date
        minutes_passed = int(mock_time_offset.total_seconds() / 60)

        if symbol in self.market.historical_data:
            data_info = self.market.historical_data[symbol]
            data = data_info['data']
            timestamps = data_info['timestamps']

            if not data.empty and timestamps is not None:
                # Calculate current position in the data (data cycles when exhausted)
                data_idx = minutes_passed % len(data)
                cycle_number = minutes_passed // len(data)
                position_in_cycle = minutes_passed % len(data)

                # Get daily aggregated data from start of day up to current time
                # Use data from beginning of day up to current position
                daily_data = data.iloc[:data_idx + 1]  # from start to current position

                if len(daily_data) > 0:
                    # Calculate daily OHLCV
                    daily_open = daily_data['Open'].iloc[0].item()  # first open of the day
                    daily_close = daily_data['Close'].iloc[-1].item()  # current close (last available)
                    daily_high = daily_data['High'].max().item()  # highest high of the day so far
                    daily_low = daily_data['Low'].min().item()  # lowest low of the day so far
                    current_volume = daily_data['Volume'].iloc[-1].item()  # current volume (not cumulative)

                    # Current real-time price (last close)
                    # Round all prices to 2 decimal places for consistency
                    current_price = round(daily_close, 2)
                    daily_open = round(daily_open, 2)
                    daily_high = round(daily_high, 2)
                    daily_low = round(daily_low, 2)

                    snapshot = Snapshot(
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
                        buy_volume=int(current_volume // 10),  # estimated current bid volume
                        sell_price=round(current_price + 0.5, 2),
                        sell_volume=int(current_volume // 10),  # estimated current ask volume
                    )
                    return snapshot

        # use fallback if no historical data
        print(f"No historical data for {symbol} at {adjusted_mock_time}, using fallback")
        return self._create_fallback_snapshot(symbol, adjusted_mock_time)

    def list_positions(self) -> List[Position]:
        """Get current positions by aggregating fill_history and updating prices."""
        # 1. Reconstruct positions from fill history
        self._reconstruct_positions_from_history()

        # 2. Update prices for the newly aggregated positions
        self._update_position_prices()

        return self.account_state.positions


    # Just to clarify, `list_trades()` is for lsodr (list order).
    # since last time I think this might be a duplicate of `list_positions()`
    # which is totally wrong :)
    def list_trades(self) -> List[Trade]:
        self._check_if_any_order_filled()

        # return all orders (placed / committed / filled / cancelled)
        trades = []
        all_orders = (self.account_state.orders_placed +
                     self.account_state.orders_committed +
                     self.account_state.orders_filled +
                     self.account_state.orders_cancelled)
        for order in all_orders:
            order_info = Trade(
                id=order.id,
                symbol=order.product.symbol,
                action=order.action.value,
                quantity=order.quantity,
                price=order.price,
                status=self.account_state.all_order_status.get(order.id, OrderStatus.UNKNOWN).value,
                order_type=order.order_type.value,
                price_type=order.price_type.value,
                order_lot=order.order_lot,
                order_datetime=order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                deals=0, # TODO: Not sure what this field means in SJ
                ordno=order.id
            )
            trades.append(order_info)
        return trades

    # TODO: Check with account balance or trading limit before placing order
    def place_order(self, order: Order) -> OrderResult:
        if not self._is_valid_price(order):
            return REJECTED_ORDER_NEGATIVE_PRICE(order)
        if not self._is_valid_quantity(order):
            return REJECTED_ORDER_NEGATIVE_QUANTITY(order)

        # Check account balance / inventory stock / trading limit per day
        if not self._is_within_trading_limit(order):
            return REJECTED_ORDER_EXCEED_TRADING_LIMIT(order)

        if order.action == OrderAction.BUY:
            if not self._is_sufficient_account_balance(order):
                return REJECTED_ORDER_NOT_SUFFICIENT_BALANCE(order)
        elif order.action == OrderAction.SELL:
            if not self._is_sufficient_account_inventory(order):
                return REJECTED_ORDER_NOT_SUFFICIENT_STOCK(order)

        # This is for checking order fill status later
        order.opt_field['last_check_for_fill'] = self.market.get_market_time()['mock_current_time']

        self.account_state.orders_placed.append(order)
        self.account_state.all_order_status[order.id] = OrderStatus.NEW
        return PLACED_ORDER_STANDARD(order)

    # Note: Commit one order at a time (which differs from Sinopac's all-at-once commit)
    def commit_order(self, order_id: str) -> OrderResult:
        order = next((o for o in self.account_state.orders_placed if o.id == order_id), None)
        if not order:
            return REJECTED_ORDER_NOT_FOUND_FOR_COMMIT(order_id)

        self.account_state.orders_committed.append(order)
        self.account_state.orders_placed.remove(order)

        # Status depends on market hours (mimics Sinopac behavior)
        if self.market.is_market_open():
            # Market open: order immediately committed to exchange
            self.account_state.all_order_status[order.id] = OrderStatus.COMMITTED
            status = OrderStatus.COMMITTED
        else:
            # Market closed: order pending, will be sent when market opens
            self.account_state.all_order_status[order.id] = OrderStatus.ON_THE_WAY
            status = OrderStatus.ON_THE_WAY

        res = OrderResult(
            status=status,
            message="Order committed successfully." if status == OrderStatus.COMMITTED else "Order pending market open.",
            metadata={"market_open": self.market.is_market_open()},
            linked_order=order.id
        )
        # print(res)
        return res

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order that is not yet filled.

        Args:
            order_id: ID of the order to cancel

        Returns:
            OrderResult with success status
        """
        # Check if order exists and is not filled
        order_to_cancel = None
        source_list = None

        # Search in orders_placed
        for order in self.account_state.orders_placed:
            if order.id == order_id:
                order_to_cancel = order
                source_list = self.account_state.orders_placed
                break

        # Search in orders_committed if not found
        if not order_to_cancel:
            for order in self.account_state.orders_committed:
                if order.id == order_id:
                    order_to_cancel = order
                    source_list = self.account_state.orders_committed
                    break

        # Check if order is already filled
        if not order_to_cancel:
            for order in self.account_state.orders_filled:
                if order.id == order_id:
                    return REJECTED_ORDER_HAS_BEEN_FILLED(order)

        # Order not found at all
        if not order_to_cancel:
            return REJECTED_ORDER_NOT_FOUND_FOR_CANCEL(order_id)

        # Remove from source list and add to cancelled
        source_list.remove(order_to_cancel)
        self.account_state.orders_cancelled.append(order_to_cancel)

        # Update order status
        self.account_state.all_order_status[order_id] = OrderStatus.CANCELLED

        print(f"Order {order_id} cancelled successfully")
        return CANCELLED_ORDER_STANDARD(order_to_cancel)

    ########################   Functions for mock_broker_api to call (end)   #########################



    ########################   Internal functions (start)   ########################
    def _is_sufficient_account_balance(self, order: Order) -> bool:
        # Check if the account has enough balance to place the order
        required_amount = order.price * order.quantity
        if self.account_state.balance >= required_amount:
            return True
        else:
            # print(f"Insufficient balance to place BUY order {order.id}: requires {required_amount}, available {self.account_state.balance}")
            return False

    def _is_sufficient_account_inventory(self, order: Order) -> bool:
        # Check if the account has enough inventory to place the SELL order
        position = next((pos for pos in self.account_state.positions if pos.symbol == order.product.symbol), None)
        if position and position.quantity >= order.quantity:
            return True
        else:
            available_qty = position.quantity if position else 0
            # print(f"Insufficient inventory to place SELL order {order.id}: requires {order.quantity}, available {available_qty}")
            return False

    # Currently we only check if the price is positive
    def _is_valid_price(self, order: Order) -> bool:
        return order.price > 0

    def _is_valid_quantity(self, order: Order) -> bool:
        return order.quantity > 0

    def _is_within_trading_limit(self, order: Order) -> bool:
        # Default trading limit per day
        TRADE_LIMIT = 1_000_000.0  # 1 million
        # Accumulate today's traded cost for all orders
        odrs = self.list_trades()
        today_str = self.market.get_market_time()['mock_current_time'].strftime('%Y-%m-%d')
        sum = 0.0
        for odr in odrs:
            # Consider committed + filled + this order
            if odr.status in [OrderStatus.COMMITTED, OrderStatus.FILLED] and odr.order_datetime.startswith(today_str):
                sum += odr.price * odr.quantity
        return sum + (order.price * order.quantity) <= TRADE_LIMIT

    # Trigger at some important points to check if order is filled
    # since we did not implement an event-driven-based exchange simulation
    def _check_if_any_order_filled(self) -> bool:
        # iterate through all committed orders and see if any can be filled
        # (compare the mock market price since last check until current mock time)
        # Iterate over a shallow copy to avoid mutating the list while iterating
        committed_copy = list(self.account_state.orders_committed)
        for odr in committed_copy:
            target_price = odr.price
            cmp_time_range_start = odr.opt_field.get('last_check_for_fill', self.market.get_market_time()['mock_init_time'])
            cmp_time_range_end = self.market.get_market_time()['mock_current_time']

            # skip if time range not advanced
            if cmp_time_range_end <= cmp_time_range_start:
                # nothing to check; continue
                continue

            # compare target price with all unchecked kbar close prices
            price_filled = False
            if odr.action == OrderAction.BUY:
                # Buy order: filled if any close price <= target price
                price_filled = self._check_price_in_time_range(
                    odr.product.symbol, cmp_time_range_start, cmp_time_range_end, lambda p: p <= target_price
                )
            elif odr.action == OrderAction.SELL:
                # Sell order: filled if any close price >= target price
                price_filled = self._check_price_in_time_range(
                    odr.product.symbol, cmp_time_range_start, cmp_time_range_end, lambda p: p >= target_price
                )

            # Update last_check_for_fill to end of checked range to avoid rechecking
            try:
                odr.opt_field['last_check_for_fill'] = cmp_time_range_end
            except Exception:
                odr.opt_field = odr.opt_field if hasattr(odr, 'opt_field') else {}
                odr.opt_field['last_check_for_fill'] = cmp_time_range_end

            if price_filled:
                # Move order to filled list
                try:
                    self.account_state.orders_filled.append(odr)
                    # remove from committed if still present
                    if odr in self.account_state.orders_committed:
                        self.account_state.orders_committed.remove(odr)
                    self.account_state.all_order_status[odr.id] = OrderStatus.FILLED
                    print(f"Order {odr.id} filled (target {target_price})")
                    qty_signed = odr.quantity if odr.action == OrderAction.BUY else -odr.quantity

                    # Update Balance (Account for cash flow)
                    # For Buy: balance decreases; For Sell: balance increases
                    # TODO: Balance should be calculated using fill history.
                    self.account_state.balance -= (qty_signed * odr.price)

                    # Record in fill history (Source of truth for positions)
                    self.account_state.fill_history.append({
                        "id": f"fill_{odr.id}_{int(datetime.datetime.now().timestamp())}",
                        "order_id": odr.id,
                        "symbol": odr.product.symbol,
                        "action": odr.action.value,
                        "quantity": qty_signed,
                        "price": odr.price,
                        "time": cmp_time_range_end.isoformat() if hasattr(cmp_time_range_end, "isoformat") else str(cmp_time_range_end)
                    })

                    # Sync the aggregated view
                    self._reconstruct_positions_from_history()
                except Exception as e:
                    print(f"Error moving order {odr.id} to filled: {e}")

    def _reconstruct_positions_from_history(self):
        """Reconstruct the aggregated positions list from fill_history."""
        if not self.account_state.fill_history:
            self.account_state.positions = []
            return

        from collections import defaultdict
        sym_fills = defaultdict(list)
        for fill in self.account_state.fill_history:
            sym_fills[fill['symbol']].append(fill)

        new_positions = []
        for sym, fills in sym_fills.items():
            net_qty = 0
            total_net_cost = 0.0

            for f in fills:
                q = f['quantity']
                p = f['price']
                net_qty += q
                total_net_cost += (q * p)

            if net_qty == 0:
                continue

            # Calculate breakeven cost
            avg_cost = total_net_cost / net_qty

            new_positions.append(Position(
                symbol=sym,
                quantity=net_qty,
                avg_cost=round(avg_cost, 2),
                current_price=round(avg_cost, 2), # Placeholder until price update
                market_value=round(net_qty * avg_cost, 1),
                unrealized_pnl=0.0
            ))

        self.account_state.positions = new_positions

    def _check_price_in_time_range(self, symbol: str, start_time: datetime.datetime, end_time: datetime.datetime, price_condition) -> bool:
        # Assume data has been preloaded
        try:
            # Ensure symbol data exists
            if symbol not in self.market.historical_data:
                return False

            data_info = self.market.historical_data[symbol]
            data = data_info.get('data')
            timestamps = data_info.get('timestamps')

            if data is None or data.empty or timestamps is None:
                return False

            # Compute minute offsets relative to market.start_date
            # Use same logic as snapshot(): map mock datetime -> minutes since start_date
            start_offset = int((start_time - self.market.start_date).total_seconds() / 60)
            end_offset = int((end_time - self.market.start_date).total_seconds() / 60)

            # Nothing to check
            if end_offset <= start_offset:
                return False

            n = len(data)
            if n == 0:
                return False

            # Iterate minute-by-minute from just after start_time up to end_time (inclusive)
            for minute in range(start_offset + 1, end_offset + 1):
                idx = minute % n  # circular replay behavior used elsewhere
                try:
                    # Prefer 'Close' column (yfinance / pandas convention)
                    # use .iat or .iloc.item() to get a scalar and avoid FutureWarning
                    try:
                        close_price = float(data['Close'].iat[idx])
                    except Exception:
                        # fallback to iloc + item
                        close_price = float(data['Close'].iloc[idx].item())
                except Exception:
                    # Fallback to uppercase/lowercase column name positional access
                    try:
                        close_price = float(data.iloc[idx]['Close'])
                    except Exception:
                        try:
                            close_price = float(data.iloc[idx]['close'])
                        except Exception:
                            # Unable to read price for this index — skip
                            continue

                if price_condition(close_price):
                    return True

            return False
        except Exception as e:
            print(f"_check_price_in_time_range error: {e}")
            return False

    def _trigger_order_matching(self):
        """
        Manaully trigger order matching process.

        Because we do not have an event-driven exchange simulation,
        this function should be called periodically to check for order fills.
        otherwise it will only be checked when `snapshot()` is called. (_check_if_any_order_filled)
        """
        self._check_if_any_order_filled()

    def _update_position_prices(self):
        """Update current_price, market_value, and unrealized_pnl for all positions.

        This method should be called whenever you need fresh prices from the simulation.
        It doesn't modify the position structure (symbol, quantity, avg_cost),
        only updates the price-related fields.
        """
        if not self.account_state.positions:
            return

        updated_positions = []
        for pos in self.account_state.positions:
            try:
                # Get current price from simulation environment
                snapshot = self.snapshot(pos.symbol)
                simulated_price = round(snapshot.close, 2)  # Round to 2 decimal places

                # Create updated position with new price
                updated_pos = Position(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    avg_cost=round(pos.avg_cost, 2),  # Keep original cost basis, rounded
                    current_price=simulated_price,  # Update with simulated price
                    market_value=round(pos.quantity * simulated_price, 1),
                    unrealized_pnl=round((simulated_price - pos.avg_cost) * pos.quantity, 1)
                )
                updated_positions.append(updated_pos)

            except Exception as e:
                # If price update fails, keep original position
                print(f"Warning: Failed to update price for {pos.symbol}: {e}")
                updated_positions.append(pos)

        self.account_state.positions = updated_positions

    def _sync_with_real_account(self):
        """Sync position structure from real account (one-time initialization).

        Strategy:
        1. Get positions (symbol, quantity, avg_cost) from real account
        2. Preload historical data for each symbol
        3. Use _update_position_prices() to set initial prices

        After this initial sync, prices will be updated on-demand when
        list_positions() is called.
        """
        if not self.real_account:
            return

        try:
            if self.real_account.connect():
                print(f"Syncing with real account (price_mode={self.price_mode.value})...")

                # Get balance from real account
                self.account_state.balance = self.real_account.get_balance()

                # Get position structure from real account
                real_positions = self.real_account.get_positions()

                if not real_positions:
                    print("No positions in real account")
                    self.account_state.positions = []
                    self.real_account.disconnect()
                    return

                # Preload historical data for all symbols
                print(f"Loading historical data for {len(real_positions)} symbols...")
                for pos in real_positions:
                    if pos.symbol not in self.market.historical_data:
                        self.market.create_historical_market(pos.symbol)

                    """ Record as initial fill history
                    We currently assume the position state as a single fill.
                    """
                    # TODO: sinopac does NOT provide fill history API!
                    # while at the same time, in the CJTrade API, we insert a fill history
                    # to local mirror db when an order is filled. So, it will be quite
                    # challenging to deal with the data dependency issue if we need to
                    # import the fill history to `MockBackend`, either (1) it reads from local
                    # mirror db (which is BAD and not make sense because why would a broker
                    # backend need the transaction data from an user?), or (2) we just do a
                    # dependency injection to ONLY pass the history from `MockBrokerAPI` to here.
                    self.account_state.fill_history.append({
                        "id": f"init_{pos.symbol}_{int(datetime.datetime.now().timestamp())}",
                        "order_id": "manual_sync",
                        "symbol": pos.symbol,
                        "action": "BUY", # Assume buy for initial positions
                        "quantity": pos.quantity,
                        "price": pos.avg_cost,
                        "time": "initial_sync"
                    })

                # Sync aggregated view
                self._reconstruct_positions_from_history()
                self.real_account.disconnect()

                # Update prices using simulation data
                self._update_position_prices()

                # Print summary
                total_value = sum(p.market_value for p in self.account_state.positions)
                total_pnl = sum(p.unrealized_pnl for p in self.account_state.positions)
                # print(f"✓ Synced: Balance=${self.account_state.balance:,.0f}, "
                #       f"Positions={len(self.account_state.positions)}")
                # for pos in self.account_state.positions:
                #     print(f"  {pos.symbol}: qty={pos.quantity}, "
                #           f"cost={pos.avg_cost:.2f}, "
                #           f"price={pos.current_price:.2f}, "
                #           f"pnl={pos.unrealized_pnl:+.2f}")
                # print(f"  Total: Value=${total_value:,.0f}, PnL=${total_pnl:+,.0f}")
            else:
                print("Failed to connect to real account for sync")
        except Exception as e:
            print(f"Error syncing with real account: {e}")

    # Read from a local JSON file to sync mock account state
    def _sync_with_mock_account_file(self):
        """Load account state from JSON file and update prices from simulation.

        Strategy:
        1. Load balance and position structure (symbol, quantity, avg_cost) from file
        2. Preload historical data for each symbol
        3. Use _update_position_prices() to set current prices from simulation

        This ensures consistency with _sync_with_real_account() logic.
        """
        import json
        from cjtrade.models.product import Product, ProductType, Exchange
        from cjtrade.models.order import OrderAction, PriceType, OrderType, OrderLot

        if not os.path.exists(self.account_state_default_file):
            default_data = {
                "balance": 100_000.0,
                "positions": [],
                "orders_placed": [],
                "orders_committed": [],
                "orders_filled": [],
                "orders_cancelled": [],
                "all_order_status": {}
            }
            with open(self.account_state_default_file, 'w') as f:
                json.dump(default_data, f, indent=4)

        with open(self.account_state_default_file, 'r') as f:
            data = json.load(f)
            self.account_state.balance = data.get('balance', 100_000.0)
            self.account_state.fill_history = data.get('fill_history', [])

            # Compute positions from fill history
            self._reconstruct_positions_from_history()

            # Preload historical data for all symbols
            if self.account_state.positions:
                for pos in self.account_state.positions:
                    if pos.symbol not in self.market.historical_data:
                        self.market.create_historical_market(pos.symbol)

            self.account_state.orders_placed = []
            for order_data in data.get('orders_placed', []):
                # Handle order_lot - could be boolean or string
                order_lot_value = order_data['order_lot']
                if isinstance(order_lot_value, bool):
                    order_lot = OrderLot.IntraDayOdd if order_lot_value else OrderLot.Common
                else:
                    order_lot = OrderLot(order_lot_value)

                order = Order(
                    id=order_data['id'],
                    product=Product(symbol=order_data['symbol']),
                    action=OrderAction(order_data['action']),
                    price=order_data['price'],
                    quantity=order_data['quantity'],
                    price_type=PriceType(order_data['price_type']),
                    order_type=OrderType(order_data['order_type']),
                    order_lot=order_lot,
                    created_at=datetime.datetime.fromisoformat(order_data['created_at'])
                )
                self.account_state.orders_placed.append(order)

            self.account_state.orders_committed = []
            for order_data in data.get('orders_committed', []):
                # Handle order_lot - could be boolean or string
                order_lot_value = order_data['order_lot']
                if isinstance(order_lot_value, bool):
                    order_lot = OrderLot.IntraDayOdd if order_lot_value else OrderLot.Common
                else:
                    order_lot = OrderLot(order_lot_value)

                order = Order(
                    id=order_data['id'],
                    product=Product(symbol=order_data['symbol']),
                    action=OrderAction(order_data['action']),
                    price=order_data['price'],
                    quantity=order_data['quantity'],
                    price_type=PriceType(order_data['price_type']),
                    order_type=OrderType(order_data['order_type']),
                    order_lot=order_lot,
                    created_at=datetime.datetime.fromisoformat(order_data['created_at'])
                )
                self.account_state.orders_committed.append(order)

            self.account_state.orders_filled = []
            for order_data in data.get('orders_filled', []):
                # Handle order_lot - could be boolean or string
                order_lot_value = order_data['order_lot']
                if isinstance(order_lot_value, bool):
                    order_lot = OrderLot.IntraDayOdd if order_lot_value else OrderLot.Common
                else:
                    order_lot = OrderLot(order_lot_value)

                order = Order(
                    id=order_data['id'],
                    product=Product(symbol=order_data['symbol']),
                    action=OrderAction(order_data['action']),
                    price=order_data['price'],
                    quantity=order_data['quantity'],
                    price_type=PriceType(order_data['price_type']),
                    order_type=OrderType(order_data['order_type']),
                    order_lot=order_lot,
                    created_at=datetime.datetime.fromisoformat(order_data['created_at'])
                )
                self.account_state.orders_filled.append(order)

            self.account_state.orders_cancelled = []
            for order_data in data.get('orders_cancelled', []):
                # Handle order_lot - could be boolean or string
                order_lot_value = order_data['order_lot']
                if isinstance(order_lot_value, bool):
                    order_lot = OrderLot.IntraDayOdd if order_lot_value else OrderLot.Common
                else:
                    order_lot = OrderLot(order_lot_value)

                order = Order(
                    id=order_data['id'],
                    product=Product(symbol=order_data['symbol']),
                    action=OrderAction(order_data['action']),
                    price=order_data['price'],
                    quantity=order_data['quantity'],
                    price_type=PriceType(order_data['price_type']),
                    order_type=OrderType(order_data['order_type']),
                    order_lot=order_lot,
                    created_at=datetime.datetime.fromisoformat(order_data['created_at'])
                )
                self.account_state.orders_cancelled.append(order)

            self.account_state.all_order_status = {
                order_id: OrderStatus(status)
                for order_id, status in data.get('all_order_status', {}).items()
            }

            # Clean up cancelled orders older than 30 minutes
            now = datetime.datetime.now()
            self.account_state.orders_cancelled = [
                order for order in self.account_state.orders_cancelled
                if (now - order.created_at).total_seconds() < 1800  # 30 minutes = 1800 seconds
            ]
            # Remove from all_order_status as well
            cancelled_order_ids = [order.id for order in self.account_state.orders_cancelled]
            self.account_state.all_order_status = {
                order_id: status
                for order_id, status in self.account_state.all_order_status.items()
                if order_id in cancelled_order_ids or status != OrderStatus.CANCELLED
            }

        # Update position prices from simulation (consistent with _sync_with_real_account)
        if self.account_state.positions:
            self._update_position_prices()

    def _create_fallback_snapshot(self, symbol: str, timestamp: datetime.datetime) -> Snapshot:
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

    ### TODO: Use these function for interval that yfinance doesn't support
    ### YFinance supports: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
    ### Sinopac supports: N/A (Only 1m kbar)
    ### Broker interface requires: 1m,3m,5m,10m,15m,20m,30m,45m,1h,90m,2h,1d,1w,1M
    def _aggregate_kbars_internal(self, kbars: List[Kbar], target_interval: str) -> List[Kbar]:
        if not kbars:
            return []

        # Simple aggregation for common intervals
        interval_minutes = {
            "3m": 3, "6m": 6, "12m": 12, "20m": 20, "45m": 45
        }

        if target_interval not in interval_minutes:
            raise ValueError(f"Mock broker: Unsupported interval for aggregation: {target_interval}")

        target_mins = interval_minutes[target_interval]

        # Group kbars by time windows and aggregate
        import pandas as pd

        data = {
            'timestamp': [k.timestamp for k in kbars],
            'open': [k.open for k in kbars],
            'high': [k.high for k in kbars],
            'low': [k.low for k in kbars],
            'close': [k.close for k in kbars],
            'volume': [k.volume for k in kbars],
        }
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)

        # Aggregate with pandas resample
        freq = f"{target_mins}min"  # Use 'min' instead of deprecated 'T'
        aggregated = df.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        # Convert back to Kbar objects
        result = []
        for timestamp, row in aggregated.iterrows():
            kbar = Kbar(
                timestamp=timestamp.to_pydatetime(),
                open=round(row['open'], 2),
                high=round(row['high'], 2),
                low=round(row['low'], 2),
                close=round(row['close'], 2),
                volume=int(row['volume'])
            )
            result.append(kbar)

        return result

    # TODO: Remove this when `list_trades()` is confirmed working
    # def list_trades_legacy(self) -> List[Dict]:
    #     self._check_if_any_order_filled()

    #     # return all orders (placed / committed / filled / cancelled)
    #     trades = []
    #     all_orders = (self.account_state.orders_placed +
    #                  self.account_state.orders_committed +
    #                  self.account_state.orders_filled +
    #                  self.account_state.orders_cancelled)
    #     for order in all_orders:
    #         order_info = {
    #             'id': order.id,
    #             'symbol': order.product.symbol,
    #             'action': order.action.value,
    #             'quantity': order.quantity,
    #             'price': order.price,
    #             'status': self.account_state.all_order_status.get(order.id, OrderStatus.UNKNOWN).value,
    #             'order_type': order.order_type.value,
    #             'price_type': order.price_type.value,
    #             'order_lot': order.order_lot,
    #             'order_datetime': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
    #             'deals': 0, # TODO: Not sure what this field means in SJ
    #             'ordno': order.id
    #         }
    #         trades.append(order_info)
    #     return trades
    ########################   Internal functions (end)   ##########################