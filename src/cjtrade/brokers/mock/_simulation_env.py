from cjtrade.core.account_client import AccountClient
from cjtrade.models.quote import Snapshot
from cjtrade.models.order import OrderAction
from cjtrade.models.kbar import Kbar
from typing import List
import yfinance as yf
import datetime
import random
import pandas as pd
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
class SimulationEnvironment:
    def __init__(self, real_account: AccountClient = None):
        self.real_account = real_account
        self.account_balance = 100_000.0  # default amount of cash
        self.positions = []
        self._connected = False

        self._init_time = datetime.datetime.now()   # For simulating time progression

        # yfinance api only keeps minute data within the last 30 days
        current_time = datetime.datetime.now()
        days_back = random.randint(1, 20)  # 1-20 days back
        start_date = current_time - datetime.timedelta(days=days_back)

        while start_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            days_back += 1
            start_date = current_time - datetime.timedelta(days=days_back)

        start_hour = random.randint(9, 13)
        if start_hour == 13:
            start_minute = random.randint(0, 30)
        else:
            start_minute = random.randint(0, 59)

        self._data_start_time = start_date.replace(
            hour=start_hour,
            minute=start_minute,
            second=0,
            microsecond=0
        )

        self._historical_data = {}  # {symbol: DataFrame}
        self._data_loaded = set()   # symbols with data loaded

        print(f"Simulation environment initialized with data starting from: {self._data_start_time}")
        print(f"(Using data from {days_back} days ago to ensure availability)")

    def start(self) -> bool:
        try:
            self._connected = True

            if self.real_account:
                self._sync_with_real_account()

            print("Simulation environment started")
            return True
        except Exception as e:
            print(f"Failed to start simulation environment: {e}")
            self._connected = False
            return False

    def stop(self):
        self._connected = False
        print("Simulation environment stopped")

    def _sync_with_real_account(self):
        if not self.real_account:
            return

        try:
            if self.real_account.connect():
                print("Syncing simulation environment with real account data...")
                self.account_balance = self.real_account.get_balance()
                self.positions = self.real_account.get_positions()
                self.real_account.disconnect()
                print(f"Synced: Balance = {self.account_balance}, Positions = {len(self.positions)}")
            else:
                print("Failed to connect to real account for sync")
        except Exception as e:
            print(f"Error syncing with real account: {e}")

    def reset_to_real_account_state(self, account: AccountClient = None):
        if account:
            self.real_account = account
            self._sync_with_real_account()
        else:
            # Reset to default empty state
            self.account_balance = 100_000.0
            self.positions = []

    def get_account_balance(self) -> float:
        return self.account_balance

    def is_connected(self) -> bool:
        return self._connected

    def _preload_historical_data(self, symbol: str):
        if symbol in self._data_loaded:
            return

        print(f"Loading historical data for {symbol}...")

        yf_symbol = f"{symbol}.TW"
        start_date = self._data_start_time
        end_date = start_date + datetime.timedelta(days=1)  # preload 1 day of data

        try:
            data = yf.download(yf_symbol,
                             start=start_date.strftime("%Y-%m-%d"),
                             end=end_date.strftime("%Y-%m-%d"),
                             interval="1m",
                             progress=False)

            if data.empty:
                print(f"No 1m data available for {symbol}, trying 1h data...")
                data = yf.download(yf_symbol,
                                 start=start_date.strftime("%Y-%m-%d"),
                                 end=end_date.strftime("%Y-%m-%d"),
                                 interval="1h",
                                 progress=False)

            if not data.empty:
                if not isinstance(data.index, pd.DatetimeIndex):
                    data.index = pd.to_datetime(data.index)

                if data.index.tz is not None:
                    if str(data.index.tz) in ['UTC', 'UTC+00:00']:
                        import pytz
                        taiwan_tz = pytz.timezone('Asia/Taipei')
                        data.index = data.index.tz_convert(taiwan_tz).tz_localize(None)
                    else:
                        data.index = data.index.tz_localize(None)

                self._historical_data[symbol] = {
                    'data': data,
                    'timestamps': data.index.to_numpy(),  # convert to numpy array for performance
                }

                print(f"Loaded {len(data)} data points for {symbol}")
            else:
                print(f"No data available for {symbol}, will use fallback")
                self._historical_data[symbol] = {
                    'data': pd.DataFrame(),
                    'timestamps': None
                }

        except Exception as e:
            print(f"Error loading data for {symbol}: {e}")
            self._historical_data[symbol] = {
                'data': pd.DataFrame(),
                'timestamps': None
            }

        self._data_loaded.add(symbol)

    # Note: This snapshot is actually a 1-min kbar
    def get_dummy_snapshot(self, symbol: str) -> Snapshot:
        if symbol not in self._data_loaded:
            self._preload_historical_data(symbol)

        current_time = datetime.datetime.now()
        time_offset = current_time - self._init_time
        sampling_time = self._data_start_time + time_offset

        minutes_passed = int(time_offset.total_seconds() / 60)

        if symbol in self._historical_data:
            data_info = self._historical_data[symbol]
            data = data_info['data']
            timestamps = data_info['timestamps']

            if not data.empty and timestamps is not None:
                # Calculate current position in the data
                data_idx = minutes_passed % len(data)
                cycle_number = minutes_passed // len(data)
                position_in_cycle = minutes_passed % len(data)

                print(f"Debug: minutes_passed={minutes_passed} (cycle {cycle_number}, position {position_in_cycle}/{len(data)}), "
                      f"simulated_time={sampling_time}")

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
                    current_price = daily_close

                    snapshot = Snapshot(
                        symbol=symbol,
                        exchange="TSE",
                        timestamp=sampling_time,
                        open=daily_open,
                        close=current_price,
                        high=daily_high,
                        low=daily_low,
                        volume=int(current_volume),
                        average_price=(daily_high + daily_low) / 2,
                        action=OrderAction.BUY if current_price >= daily_open else OrderAction.SELL,
                        buy_price=current_price,
                        buy_volume=int(current_volume // 10),  # estimated current bid volume
                        sell_price=current_price + 0.5,
                        sell_volume=int(current_volume // 10),  # estimated current ask volume
                    )
                    return snapshot

        # use fallback if no historical data
        print(f"No historical data for {symbol} at {sampling_time}, using fallback")
        return self._create_fallback_snapshot(symbol, sampling_time)

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

    def get_dummy_kbars(self, symbol: str, start: str, end: str, interval: str = "1m") -> List[Kbar]:
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

    # TODO: Remove this when get_dummy_kbars() is stable
    # Legacy method for backward compatibility - now just returns single kbar
    # Note that it originate from old get_dummy_snapshot() behavior return only one snapshot info.
    def get_dummy_kbar(self, symbol: str) -> Kbar:
        if symbol not in self._data_loaded:
            self._preload_historical_data(symbol)

        current_time = datetime.datetime.now()
        time_offset = current_time - self._init_time
        sampling_time = self._data_start_time + time_offset

        minutes_passed = int(time_offset.total_seconds() / 60)

        if symbol in self._historical_data:
            data_info = self._historical_data[symbol]
            data = data_info['data']
            timestamps = data_info['timestamps']

            if not data.empty and timestamps is not None:
                # CIRCULARLY replay historical data
                data_idx = minutes_passed % len(data)

                actual_data_time = data.index[data_idx]
                cycle_number = minutes_passed // len(data)
                position_in_cycle = minutes_passed % len(data)

                print(f"Debug: minutes_passed={minutes_passed} (cycle {cycle_number}, position {position_in_cycle}/{len(data)}), "
                      f"historical_data_time={actual_data_time}, simulated_time={sampling_time}")

                row = data.iloc[data_idx]

                open_price = round(row['Open'].item(), 2)
                close_price = round(row['Close'].item(), 2)
                high_price = round(row['High'].item(), 2)
                low_price = round(row['Low'].item(), 2)
                volume = row['Volume'].item()

                kbar = Kbar(
                    timestamp=sampling_time,
                    open=open_price,
                    close=close_price,
                    high=high_price,
                    low=low_price,
                    volume=int(volume),
                )
                return kbar

        # use fallback if no historical data
        print(f"No historical data for {symbol} at {sampling_time}, using fallback")
        return None