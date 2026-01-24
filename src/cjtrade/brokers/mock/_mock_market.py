import os
from enum import Enum
from cjtrade.core.account_client import AccountClient
from cjtrade.models.position import Position
from cjtrade.models.product import Product
from cjtrade.models.quote import Snapshot
from cjtrade.models.order import Order, OrderAction, OrderResult, OrderStatus
from cjtrade.models.kbar import Kbar
from typing import Dict, List
import yfinance as yf
import datetime
import random
import pandas as pd

# Acts as HistoricalPriceEngine - replays historical market data
# Future: Can create SyntheticPriceEngine as alternative implementation
class MockBackend_MockMarket:
    def __init__(self, real_account: AccountClient = None):
        self.historical_data = {}     # {symbol: {'data': DataFrame, 'timestamps': numpy_array}}
        self.playback_speed = 1.0     # 1x real-time speed (play N kbars per minute)
        self.real_init_time = 0       # real_current_time - real_init_time = time_offset
        self.mock_init_time = 0       # mock_init_time + time_offset = mock_current_time
        self.start_date = 0
        self.real_account = real_account if real_account else None

    def set_playback_speed(self, speed: float):
        """
        When changing playback speed, we:
        1. Calculate mock_current_time with old speed
        2. Reset real_init_time to now
        3. Reset start_date to current mock_current_time
        4. Update playback_speed
        """
        # 1 second in real world corresponds to `speed` seconds in mock world
        supported_speeds = [0.5, 1.0, 2.0, 5.0, 10.0,
                            30.0, 60.0, 120.0, 600.0,
                            1200.0, 3000.0, 6000.0]
        if speed not in supported_speeds:
            raise ValueError(f"Unsupported playback speed: {speed}. Supported speeds: {supported_speeds}")

        # Recalibrate time baseline to prevent time jumps when changing speed
        if hasattr(self, 'real_init_time') and self.real_init_time != 0:
            # Calculate current mock time with old speed
            real_current_time = datetime.datetime.now()
            time_offset = real_current_time - self.real_init_time
            mock_current_time = self.start_date + time_offset * self.playback_speed

            # Reset baseline: use current mock time as new start_date
            self.start_date = mock_current_time
            self.real_init_time = real_current_time

        self.playback_speed = speed

    def set_historical_time(self, real_init_time: datetime.datetime, days_back: int = 10):
        # yfinance api only keeps minute data within the last 30 days
        self.real_init_time = real_init_time

        real_current_time = self.real_init_time
        self.start_date = real_current_time - datetime.timedelta(days=days_back)
        self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

        # Skip weekends - make sure to keep hour=9 after recalculation
        while self.start_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            days_back += 1
            self.start_date = real_current_time - datetime.timedelta(days=days_back)
            self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

    def get_market_time(self):
        real_current_time = datetime.datetime.now()
        time_offset = real_current_time - self.real_init_time
        mock_current_time = self.start_date + time_offset * self.playback_speed
        return {
            'real_current_time': real_current_time,
            'real_init_time': self.real_init_time,
            'mock_init_time': self.start_date,
            'mock_current_time': mock_current_time,
            'time_offset': time_offset,
            'playback_speed': self.playback_speed
        }

    def adjust_to_market_hours(self, mock_current_time: datetime.datetime) -> datetime.datetime:
        """Adjust mock time to market hours (9:00-13:30).

        If time is after 13:30, return 13:30 of the same day (market close).
        If time is before 9:00, return 13:30 of the previous trading day.
        Otherwise, return the original time.

        Args:
            mock_current_time: The current mock time to check

        Returns:
            Adjusted time within market hours or at market close
        """
        # Market hours: 9:00 - 13:30
        market_open_hour = 9
        market_open_minute = 0
        market_close_hour = 13
        market_close_minute = 30

        current_time_of_day = mock_current_time.time()
        market_open_time = datetime.time(market_open_hour, market_open_minute)
        market_close_time = datetime.time(market_close_hour, market_close_minute)

        # If after market close (after 13:30), freeze at 13:30 of same day
        if current_time_of_day > market_close_time:
            adjusted_time = mock_current_time.replace(
                hour=market_close_hour,
                minute=market_close_minute,
                second=0,
                microsecond=0
            )
            return adjusted_time

        # If before market open (before 9:00), use previous trading day's close (13:30)
        if current_time_of_day < market_open_time:
            # Go to previous day
            prev_day = mock_current_time - datetime.timedelta(days=1)
            # Skip weekends
            while prev_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
                prev_day = prev_day - datetime.timedelta(days=1)
            adjusted_time = prev_day.replace(
                hour=market_close_hour,
                minute=market_close_minute,
                second=0,
                microsecond=0
            )
            return adjusted_time

        # Within market hours, return as is
        return mock_current_time

    def create_historical_market(self, symbol: str):
        """Load historical market data for a symbol.

        Data source priority:
        1. Real account (if available) - via get_kbars()
        2. Yahoo Finance - as fallback

        Args:
            symbol: Stock symbol to load data for
        """
        # Early return if data already loaded
        if symbol in self.historical_data:
            return

        NUM_DAYS_PRELOAD = 5
        end_date = self.start_date + datetime.timedelta(days=NUM_DAYS_PRELOAD)

        # Load historical data from real account for better data quality
        if self.real_account and self.real_account.is_connected():
            self._load_from_real_account(symbol, end_date)
        else:
            self._load_from_yahoo_finance(symbol, end_date)

    def _load_from_real_account(self, symbol: str, end_date: datetime.datetime):
        """Load historical data from real broker account."""
        print(f"Loading historical data for {symbol}... (source: {self.real_account.get_broker_name()})")
        try:
            kbars = self.real_account.get_kbars(
                Product(symbol=symbol),
                start=self.start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1m"
            )

            # Convert kbars to DataFrame
            df = pd.DataFrame([{
                'Open': kbar.open,
                'High': kbar.high,
                'Low': kbar.low,
                'Close': kbar.close,
                'Volume': kbar.volume
            } for kbar in kbars], index=[kbar.timestamp for kbar in kbars])

            if not df.empty:
                self.historical_data[symbol] = {
                    'data': df,
                    'timestamps': df.index.to_numpy(),
                }
                print(f"Loaded {len(df)} data points for {symbol} from real account")
            else:
                self._store_empty_data(symbol, "No data from real account")

        except Exception as e:
            print(f"Error loading data from real account for {symbol}: {e}")
            self._store_empty_data(symbol, str(e))

    def _load_from_yahoo_finance(self, symbol: str, end_date: datetime.datetime):
        """Load historical data from Yahoo Finance."""
        print(f"Loading historical data for {symbol}... (source: yfinance)")
        yf_symbol = f"{symbol}.TW"

        try:
            data = yf.download(
                yf_symbol,
                start=self.start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1m",
                auto_adjust=True,
                progress=False
            )

            if data.empty:
                self._store_empty_data(symbol, "No data from Yahoo Finance")
                return

            # Normalize timezone
            data = self._normalize_timezone(data)

            self.historical_data[symbol] = {
                'data': data,
                'timestamps': data.index.to_numpy(),
            }
            print(f"Loaded {len(data)} data points for {symbol}")

        except Exception as e:
            print(f"Error loading data for {symbol}: {e}")
            self._store_empty_data(symbol, str(e))

    def _normalize_timezone(self, data: pd.DataFrame) -> pd.DataFrame:
        """Normalize DataFrame timezone to naive Taiwan time."""
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index)

        if data.index.tz is not None:
            if str(data.index.tz) in ['UTC', 'UTC+00:00']:
                import pytz
                taiwan_tz = pytz.timezone('Asia/Taipei')
                data.index = data.index.tz_convert(taiwan_tz).tz_localize(None)
            else:
                data.index = data.index.tz_localize(None)

        return data

    def _store_empty_data(self, symbol: str, reason: str):
        """Store empty data placeholder with consistent structure."""
        print(f"Using empty data for {symbol}: {reason}")
        self.historical_data[symbol] = {
            'data': pd.DataFrame(),
            'timestamps': None
        }


