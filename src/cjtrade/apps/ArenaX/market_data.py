import os
import random
from datetime import datetime
from datetime import time
from datetime import timedelta
from enum import Enum
from typing import Dict
from typing import List

import pandas as pd
import yfinance as yf
from cjtrade.apps.ArenaX.price_db import ArenaX_LocalPriceDB
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot

# Price source: yfinance
class ArenaX_Market:
    def __init__(self, real_account: AccountClient = None):
        self.historical_data = {}     # {symbol: {'data': DataFrame, 'timestamps': numpy_array}}
        self.playback_speed = 1.0     # 1x real-time speed (play N kbars per minute)
        self.real_init_time = 0       # real_current_time - real_init_time = time_offset
        self.mock_init_time = 0       # mock_init_time + time_offset = mock_current_time
        self.start_date = 0
        self.real_account = real_account if real_account else None
        self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps
        # Pause/resume support
        self.paused: bool = False
        self.paused_time: datetime | None = None

        self.price_db = ArenaX_LocalPriceDB(path="data/arenax_price.db")
        self.price_db.connect()  # TODO: currently no corresponding disconnect, need to add it in the right place (maybe in ArenaX_Backend?)

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
                            1200.0, 3000.0, 6000.0, 12000.0, 30000.0]
        if speed not in supported_speeds:
            raise ValueError(f"Unsupported playback speed: {speed}. Supported speeds: {supported_speeds}")

        # Recalibrate time baseline to prevent time jumps when changing speed
        if hasattr(self, 'real_init_time') and self.real_init_time != 0:
            # Calculate current mock time with old speed
            real_current_time = datetime.now()
            time_offset = real_current_time - self.real_init_time
            mock_current_time = self.start_date + time_offset * self.playback_speed

            # Reset baseline: use current mock time as new start_date
            self.start_date = mock_current_time
            self.real_init_time = real_current_time

        self.playback_speed = speed

    def fetching_available(self, date: datetime) -> bool:
        # Currently a workaround
        if self.real_account and self.real_account.is_connected():
            return True

        data = yf.download(
            "2330.TW",
            start=date.strftime("%Y-%m-%d"),
            end=(date + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1m",
            auto_adjust=True,
            progress=False
        )
        return True if not data.empty else False


    def set_historical_time_abs(self, real_init_time: datetime, mock_init_time: datetime):
        # yfinance api only keeps minute data within the last 30 days
        self.real_init_time = real_init_time

        real_current_time = self.real_init_time
        self.start_date = mock_init_time
        self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

        # Skip weekends - make sure to keep hour=9 after recalculation
        adjustment = 0
        while self.start_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            adjustment += 1
            self.start_date = mock_init_time - timedelta(days=adjustment)
            self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

    # Alias
    def set_historical_time_rel(self, real_init_time: datetime, days_back: int = 10):
        self.set_historical_time(real_init_time, days_back)

    def set_historical_time(self, real_init_time: datetime, days_back: int = 10):
        # yfinance api only keeps minute data within the last 30 days
        self.real_init_time = real_init_time

        real_current_time = self.real_init_time
        self.start_date = real_current_time - timedelta(days=days_back)
        self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

        # Skip weekends - make sure to keep hour=9 after recalculation
        while self.start_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            days_back += 1
            self.start_date = real_current_time - timedelta(days=days_back)
            self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

    def adjust_time(self, hours: float):
        """Manually adjust mock time by specified hours.

        Args:
            hours: Number of hours to shift (can be negative)
        """
        self.manual_time_offset += timedelta(hours=hours)
        # print(f"Mock time adjusted by {hours:+.1f} hours")
        # print(f"Total manual offset: {self.manual_time_offset.total_seconds() / 3600:+.1f} hours")

    def get_market_time(self):
        real_current_time = datetime.now()
        # If paused, return the frozen paused_time as mock_current_time
        if self.paused and self.paused_time is not None:
            mock_current_time = self.paused_time
            time_offset = mock_current_time - self.start_date
        else:
            time_offset = real_current_time - self.real_init_time
            mock_current_time = self.start_date + time_offset * self.playback_speed + self.manual_time_offset

        return {
            'real_current_time': real_current_time,
            'real_init_time': self.real_init_time,
            'mock_init_time': self.start_date,
            'mock_current_time': mock_current_time,
            'time_offset': time_offset,
            'playback_speed': self.playback_speed,
            'manual_time_offset': self.manual_time_offset,
            'paused': self.paused,
        }

    def _compute_raw_mock_time(self) -> datetime:
        """Compute mock time using current formula (ignores paused flag)."""
        real_current_time = datetime.now()
        time_offset = real_current_time - self.real_init_time
        return self.start_date + time_offset * self.playback_speed + self.manual_time_offset

    def pause_time_progress(self) -> datetime:
        """Freeze mock time at current value.

        Returns the paused mock_current_time.
        """
        if not self.paused:
            self.paused_time = self._compute_raw_mock_time()
            self.paused = True
        return self.paused_time

    def resume_time_progress(self) -> datetime:
        """Resume time progression.

        This sets the paused_time as the new start_date baseline and resets real_init_time
        so that mock time continues from the frozen point.
        Returns the new mock_current_time baseline (same as previous paused_time).
        """
        if not self.paused:
            return self._compute_raw_mock_time()

        baseline = self.paused_time or self._compute_raw_mock_time()
        # Rebase timeline so no jump occurs and pause duration is ignored
        self.start_date = baseline
        self.real_init_time = datetime.now()
        self.paused_time = None
        self.paused = False
        return baseline

    def adjust_to_market_hours(self, mock_current_time: datetime) -> datetime:
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
        market_open_time = time(market_open_hour, market_open_minute)
        market_close_time = time(market_close_hour, market_close_minute)

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
            prev_day = mock_current_time - timedelta(days=1)
            # Skip weekends
            while prev_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
                prev_day = prev_day - timedelta(days=1)
            adjusted_time = prev_day.replace(
                hour=market_close_hour,
                minute=market_close_minute,
                second=0,
                microsecond=0
            )
            return adjusted_time

        # Within market hours, return as is
        return mock_current_time

    def is_market_open(self) -> bool:
        """Check if market is currently open (9:00-13:30 on weekdays)

        Returns:
            True if within market hours, False otherwise
        """
        mock_current_time = self.get_market_time()['mock_current_time']

        # Check if weekend
        if mock_current_time.weekday() >= 5:  # Saturday or Sunday
            return False

        # Market hours: 9:00 - 13:30
        current_time = mock_current_time.time()
        market_open = time(9, 0)
        market_close = time(13, 30)

        return market_open <= current_time <= market_close

    # TODO: Check if the gap filling mechanism really work and is with correct timezone
    def create_historical_market(self, symbol: str, days_preload: int = 5):
        """Load historical market data for a symbol with gap-aware caching.

        Strategy
        --------
        1. Compute which sub-intervals of [start_date, end_date] are NOT yet cached
           in the local price DB (``arenax_symbol_coverage``).
        2. For every missing gap, fetch from ``real_account`` (preferred) or yfinance,
           persist every fetched kbar and record the covered range so subsequent calls
           skip that window.
        3. Load the full [start_date, end_date] range from the local price DB and
           build the in-memory ``historical_data`` DataFrame.

        All fetching is fill-only (``overwrite=False``) – existing cached bars are
        never overwritten unless the caller explicitly clears the DB.

        Args:
            symbol: Stock symbol to load data for.
            days_preload: Number of days beyond ``start_date`` to pre-load.
        """
        # Skip if already loaded in memory

        # print(f"create_historical_market() called for {symbol} with days_preload={days_preload}")
        if symbol in self.historical_data:
            return

        end_date = self.start_date + timedelta(days=days_preload)

        # ── 1. Identify missing ranges ───────────────────────────────────────
        if self.price_db:
            missing = self.price_db.get_missing_ranges(symbol, "1m", self.start_date, end_date)
        else:
            # No price DB – treat entire window as missing
            missing = [(int(self.start_date.timestamp()), int(end_date.timestamp()))]

        # ── 2. Fetch & cache each gap ────────────────────────────────────────
        if missing:
            print(f"[{symbol}] {len(missing)} gap(s) to fill: " +
                  ", ".join(f"[{s},{e}]" for s, e in missing))
            for gap_start_epoch, gap_end_epoch in missing:
                gap_start = datetime.fromtimestamp(gap_start_epoch)
                gap_end   = datetime.fromtimestamp(gap_end_epoch)
                self._fetch_and_cache_range(symbol, gap_start, gap_end)

        # ── 3. Load full requested range from local DB ───────────────────────
        if self.price_db:
            self._load_from_price_db(symbol, end_date)

        # Fallback: if DB load produced nothing (e.g. no price_db at all)
        if not self.historical_data.get(symbol) or self.historical_data[symbol]['data'].empty:
            self._store_empty_data(symbol, "No data after gap-fill attempt")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_and_cache_range(self, symbol: str, gap_start: datetime, gap_end: datetime):
        """Fetch kbars for [gap_start, gap_end] from the best available source,
        persist them to the local price DB, and record coverage.

        Fill-only: bars already present are *not* overwritten.
        """
        source = "yfinance"
        kbars: list = []

        if self.real_account and self.real_account.is_connected():
            source = self.real_account.get_broker_name()
            kbars = self._fetch_from_real_account(
                symbol,
                gap_start.strftime("%Y-%m-%d"),
                gap_end.strftime("%Y-%m-%d")
            )

        if not kbars:
            source = "yfinance"
            kbars = self._fetch_from_yahoo_finance(
                symbol,
                gap_start.strftime("%Y-%m-%d"),
                gap_end.strftime("%Y-%m-%d")
            )

        if not kbars:
            print(f"[{symbol}] No data available for gap [{gap_start} – {gap_end}]")
            return

        # Persist – fill only (overwrite=False keeps existing bars intact)
        if self.price_db:
            saved = self.price_db.insert_prices_batch(
                symbol, kbars, timeframe="1m", source=source, overwrite=False
            )
            print(f"[{symbol}] Cached {saved}/{len(kbars)} bars "
                  f"({gap_start.date()} – {gap_end.date()}, source={source})")

            # Record the covered range even if some bars already existed
            if kbars:
                actual_start = min(kb.timestamp for kb in kbars)
                actual_end   = max(kb.timestamp for kb in kbars)
                self.price_db.record_coverage(symbol, "1m", actual_start, actual_end, source)

    def _fetch_from_real_account(self, symbol: str,
                                  start: str, end: str,
                                  interval: str = "1m") -> list:
        """Fetch kbars from real_account; returns List[Kbar] or [] on failure."""
        try:
            kbars = self.real_account.get_kbars(
                Product(symbol=symbol), start=start, end=end, interval=interval
            )
            return kbars or []
        except Exception as exc:
            print(f"[{symbol}] real_account fetch failed ({start}–{end}): {exc}")
            return []

    def _fetch_from_yahoo_finance(self, symbol: str,
                                   start: str, end: str,
                                   interval: str = "1m") -> list:
        """Fetch kbars from yfinance; returns List[Kbar] or [] on failure."""
        yf_symbol = f"{symbol}.TW"
        try:
            data = yf.download(
                yf_symbol, start=start, end=end,
                interval=interval, auto_adjust=True, progress=False
            )
            if data.empty:
                return []
            data = self._normalize_timezone(data)
            kbars = []
            for ts, row in data.iterrows():
                kbars.append(Kbar(
                    timestamp=ts.to_pydatetime(),
                    open=round(row["Open"].item(), 2),
                    high=round(row["High"].item(), 2),
                    low=round(row["Low"].item(), 2),
                    close=round(row["Close"].item(), 2),
                    volume=int(row["Volume"].item()),
                ))
            return kbars
        except Exception as exc:
            print(f"[{symbol}] yfinance fetch failed ({start}–{end}): {exc}")
            return []

    def _load_from_price_db(self, symbol: str, end_date: datetime):
        """Load historical data from the local price database into self.historical_data."""
        print(f"[{symbol}] Loading from local price cache ({self.start_date.date()} – {end_date.date()})…")
        try:
            ks = self.price_db.get_price(
                symbol=symbol, timeframe="1m",
                start_ts=self.start_date, end_ts=end_date
            )
            if ks:
                df = pd.DataFrame([{
                    'Open':   k.open,
                    'High':   k.high,
                    'Low':    k.low,
                    'Close':  k.close,
                    'Volume': k.volume,
                } for k in ks], index=[k.timestamp for k in ks])

                self.historical_data[symbol] = {
                    'data': df,
                    'timestamps': df.index.to_numpy(),
                }
                print(f"[{symbol}] Loaded {len(df)} bar(s) from local price cache")
            else:
                print(f"[{symbol}] Local price cache empty for requested range")

        except Exception as exc:
            print(f"[{symbol}] Error loading from local price cache: {exc}")
            self._store_empty_data(symbol, str(exc))

    # NOTE: _load_from_real_account and _load_from_yahoo_finance are replaced by the
    # lower-level _fetch_from_real_account / _fetch_from_yahoo_finance helpers above,
    # which return List[Kbar] and let create_historical_market handle persistence.
    # Kept as thin stubs so external callers do not break.

    def _load_from_real_account(self, symbol: str, end_date: datetime):
        """Deprecated shim – use _fetch_and_cache_range instead."""
        self._fetch_and_cache_range(symbol, self.start_date, end_date)
        if self.price_db:
            self._load_from_price_db(symbol, end_date)

    def _load_from_yahoo_finance(self, symbol: str, end_date: datetime):
        """Deprecated shim – use _fetch_and_cache_range instead."""
        self._fetch_and_cache_range(symbol, self.start_date, end_date)
        if self.price_db:
            self._load_from_price_db(symbol, end_date)

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


# Basically this class is just for compatibility
# to provide `is_market_open()` and `get_market_time()`
class ArenaX_RealMarket:
    def __init__(self, real_account: AccountClient):
        self.real_account = real_account
        self.playback_speed = 1.0  # Real market doesn't use playback speed, but we keep the attribute for interface consistency
        self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps
        self.mock_init_time = datetime.now()  # For real market, mock_init_time is just the time when we start the simulation
        self.real_init_time = datetime.now()  # Real market time baseline

    def is_market_open(self) -> bool:
        return self.real_account.is_market_open()

    def get_market_time(self):
        return {
            "real_current_time": datetime.now(),
            "real_init_time": self.real_init_time,
            "mock_init_time": self.mock_init_time,
            "mock_current_time": datetime.now(),  # In real market, mock_current_time is
            "time_offset": datetime.now() - self.real_init_time,
            "playback_speed": self.playback_speed,
            "manual_time_offset": self.manual_time_offset
        }



################################   Legacy Code Below   #####################################
#  _                                   ____          _        ____       _                 #
# | |    ___  __ _  __ _  ___ _   _   / ___|___   __| | ___  | __ )  ___| | _____      __  #
# | |   / _ \/ _` |/ _` |/ __| | | | | |   / _ \ / _` |/ _ \ |  _ \ / _ \ |/ _ \ \ /\ / /  #
# | |__|  __/ (_| | (_| | (__| |_| | | |__| (_) | (_| |  __/ | |_) |  __/ | (_) \ V  V /   #
# |_____\___|\__, |\__,_|\___|\__, |  \____\___/ \__,_|\___| |____/ \___|_|\___/ \_/\_/    #
#            |___/            |___/                                                        #
################################   Legacy Code Below   #####################################

# Acts as HistoricalPriceEngine - replays historical market data
# Future: Can create SyntheticPriceEngine as alternative implementation
# class MockBackend_MockMarket:
#     def __init__(self, real_account: AccountClient = None):
#         self.historical_data = {}     # {symbol: {'data': DataFrame, 'timestamps': numpy_array}}
#         self.playback_speed = 1.0     # 1x real-time speed (play N kbars per minute)
#         self.real_init_time = 0       # real_current_time - real_init_time = time_offset
#         self.mock_init_time = 0       # mock_init_time + time_offset = mock_current_time
#         self.start_date = 0
#         self.real_account = real_account if real_account else None
#         self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps

#     def set_playback_speed(self, speed: float):
#         """
#         When changing playback speed, we:
#         1. Calculate mock_current_time with old speed
#         2. Reset real_init_time to now
#         3. Reset start_date to current mock_current_time
#         4. Update playback_speed
#         """
#         # 1 second in real world corresponds to `speed` seconds in mock world
#         supported_speeds = [0.5, 1.0, 2.0, 5.0, 10.0,
#                             30.0, 60.0, 120.0, 600.0,
#                             1200.0, 3000.0, 6000.0, 12000.0, 30000.0]
#         if speed not in supported_speeds:
#             raise ValueError(f"Unsupported playback speed: {speed}. Supported speeds: {supported_speeds}")

#         # Recalibrate time baseline to prevent time jumps when changing speed
#         if hasattr(self, 'real_init_time') and self.real_init_time != 0:
#             # Calculate current mock time with old speed
#             real_current_time = datetime.now()
#             time_offset = real_current_time - self.real_init_time
#             mock_current_time = self.start_date + time_offset * self.playback_speed

#             # Reset baseline: use current mock time as new start_date
#             self.start_date = mock_current_time
#             self.real_init_time = real_current_time

#         self.playback_speed = speed

#     def fetching_available(self, date: datetime) -> bool:
#         # Currently a workaround
#         if self.real_account and self.real_account.is_connected():
#             return True

#         data = yf.download(
#             "2330.TW",
#             start=date.strftime("%Y-%m-%d"),
#             end=(date + timedelta(days=1)).strftime("%Y-%m-%d"),
#             interval="1m",
#             auto_adjust=True,
#             progress=False
#         )
#         return True if not data.empty else False


#     def set_historical_time(self, real_init_time: datetime, days_back: int = 10):
#         # yfinance api only keeps minute data within the last 30 days
#         self.real_init_time = real_init_time

#         real_current_time = self.real_init_time
#         self.start_date = real_current_time - timedelta(days=days_back)
#         self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

#         # Skip weekends - make sure to keep hour=9 after recalculation
#         while self.start_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
#             days_back += 1
#             self.start_date = real_current_time - timedelta(days=days_back)
#             self.start_date = self.start_date.replace(hour=9, minute=0, second=0, microsecond=0)

#     def adjust_time(self, hours: float):
#         """Manually adjust mock time by specified hours.

#         Args:
#             hours: Number of hours to shift (can be negative)
#         """
#         self.manual_time_offset += timedelta(hours=hours)
#         print(f"Mock time adjusted by {hours:+.1f} hours")
#         print(f"Total manual offset: {self.manual_time_offset.total_seconds() / 3600:+.1f} hours")

#     def get_market_time(self):
#         real_current_time = datetime.now()
#         time_offset = real_current_time - self.real_init_time
#         mock_current_time = self.start_date + time_offset * self.playback_speed + self.manual_time_offset
#         return {
#             'real_current_time': real_current_time,
#             'real_init_time': self.real_init_time,
#             'mock_init_time': self.start_date,
#             'mock_current_time': mock_current_time,
#             'time_offset': time_offset,
#             'playback_speed': self.playback_speed,
#             'manual_time_offset': self.manual_time_offset
#         }

#     def adjust_to_market_hours(self, mock_current_time: datetime) -> datetime:
#         """Adjust mock time to market hours (9:00-13:30).

#         If time is after 13:30, return 13:30 of the same day (market close).
#         If time is before 9:00, return 13:30 of the previous trading day.
#         Otherwise, return the original time.

#         Args:
#             mock_current_time: The current mock time to check

#         Returns:
#             Adjusted time within market hours or at market close
#         """
#         # Market hours: 9:00 - 13:30
#         market_open_hour = 9
#         market_open_minute = 0
#         market_close_hour = 13
#         market_close_minute = 30

#         current_time_of_day = mock_current_time.time()
#         market_open_time = time(market_open_hour, market_open_minute)
#         market_close_time = time(market_close_hour, market_close_minute)

#         # If after market close (after 13:30), freeze at 13:30 of same day
#         if current_time_of_day > market_close_time:
#             adjusted_time = mock_current_time.replace(
#                 hour=market_close_hour,
#                 minute=market_close_minute,
#                 second=0,
#                 microsecond=0
#             )
#             return adjusted_time

#         # If before market open (before 9:00), use previous trading day's close (13:30)
#         if current_time_of_day < market_open_time:
#             # Go to previous day
#             prev_day = mock_current_time - timedelta(days=1)
#             # Skip weekends
#             while prev_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
#                 prev_day = prev_day - timedelta(days=1)
#             adjusted_time = prev_day.replace(
#                 hour=market_close_hour,
#                 minute=market_close_minute,
#                 second=0,
#                 microsecond=0
#             )
#             return adjusted_time

#         # Within market hours, return as is
#         return mock_current_time

#     def is_market_open(self) -> bool:
#         """Check if market is currently open (9:00-13:30 on weekdays)

#         Returns:
#             True if within market hours, False otherwise
#         """
#         mock_current_time = self.get_market_time()['mock_current_time']

#         # Check if weekend
#         if mock_current_time.weekday() >= 5:  # Saturday or Sunday
#             return False

#         # Market hours: 9:00 - 13:30
#         current_time = mock_current_time.time()
#         market_open = time(9, 0)
#         market_close = time(13, 30)

#         return market_open <= current_time <= market_close

#     def create_historical_market(self, symbol: str, days_preload: int = 5):
#         """Load historical market data for a symbol.

#         Data source priority:
#         1. Real account (if available) - via get_kbars()
#         2. Yahoo Finance - as fallback

#         Args:
#             symbol: Stock symbol to load data for
#         """
#         # Early return if data already loaded
#         if symbol in self.historical_data:
#             return

#         NUM_DAYS_PRELOAD = days_preload
#         end_date = self.start_date + timedelta(days=NUM_DAYS_PRELOAD)

#         # Load historical data from real account for better data quality
#         if self.real_account and self.real_account.is_connected():
#             self._load_from_real_account(symbol, end_date)
#         else:
#             self._load_from_yahoo_finance(symbol, end_date)

#     def _load_from_real_account(self, symbol: str, end_date: datetime):
#         """Load historical data from real broker account."""
#         print(f"Loading historical data for {symbol}... (source: {self.real_account.get_broker_name()})")
#         try:
#             kbars = self.real_account.get_kbars(
#                 Product(symbol=symbol),
#                 start=self.start_date.strftime("%Y-%m-%d"),
#                 end=end_date.strftime("%Y-%m-%d"),
#                 interval="1m"
#             )

#             # Convert kbars to DataFrame
#             df = pd.DataFrame([{
#                 'Open': kbar.open,
#                 'High': kbar.high,
#                 'Low': kbar.low,
#                 'Close': kbar.close,
#                 'Volume': kbar.volume
#             } for kbar in kbars], index=[kbar.timestamp for kbar in kbars])

#             if not df.empty:
#                 self.historical_data[symbol] = {
#                     'data': df,
#                     'timestamps': df.index.to_numpy(),
#                 }
#                 print(f"Loaded {len(df)} data points for {symbol} from real account")
#             else:
#                 self._store_empty_data(symbol, "No data from real account")

#         except Exception as e:
#             print(f"Error loading data from real account for {symbol}: {e}")
#             self._store_empty_data(symbol, str(e))

#     def _load_from_yahoo_finance(self, symbol: str, end_date: datetime):
#         """Load historical data from Yahoo Finance."""
#         print(f"Loading historical data for {symbol}... (source: yfinance)")
#         yf_symbol = f"{symbol}.TW"

#         try:
#             data = yf.download(
#                 yf_symbol,
#                 start=self.start_date.strftime("%Y-%m-%d"),
#                 end=end_date.strftime("%Y-%m-%d"),
#                 interval="1m",
#                 auto_adjust=True,
#                 progress=False
#             )

#             if data.empty:
#                 self._store_empty_data(symbol, "No data from Yahoo Finance")
#                 return

#             # Normalize timezone
#             data = self._normalize_timezone(data)

#             self.historical_data[symbol] = {
#                 'data': data,
#                 'timestamps': data.index.to_numpy(),
#             }
#             print(f"Loaded {len(data)} data points for {symbol}")

#         except Exception as e:
#             print(f"Error loading data for {symbol}: {e}")
#             self._store_empty_data(symbol, str(e))

#     def _normalize_timezone(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Normalize DataFrame timezone to naive Taiwan time."""
#         if not isinstance(data.index, pd.DatetimeIndex):
#             data.index = pd.to_datetime(data.index)

#         if data.index.tz is not None:
#             if str(data.index.tz) in ['UTC', 'UTC+00:00']:
#                 import pytz
#                 taiwan_tz = pytz.timezone('Asia/Taipei')
#                 data.index = data.index.tz_convert(taiwan_tz).tz_localize(None)
#             else:
#                 data.index = data.index.tz_localize(None)

#         return data

#     def _store_empty_data(self, symbol: str, reason: str):
#         """Store empty data placeholder with consistent structure."""
#         print(f"Using empty data for {symbol}: {reason}")
#         self.historical_data[symbol] = {
#             'data': pd.DataFrame(),
#             'timestamps': None
#         }


# # Basically this class is just for compatibility
# # to provide `is_market_open()` and `get_market_time()`
# class MockBackend_RealMarket:
#     def __init__(self, real_account: AccountClient):
#         self.real_account = real_account
#         self.playback_speed = 1.0  # Real market doesn't use playback speed, but we keep the attribute for interface consistency
#         self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps
#         self.mock_init_time = datetime.now()  # For real market, mock_init_time is just the time when we start the simulation
#         self.real_init_time = datetime.now()  # Real market time baseline

#     def is_market_open(self) -> bool:
#         return self.real_account.is_market_open()

#     def get_market_time(self):
#         return {
#             "real_current_time": datetime.now(),
#             "real_init_time": self.real_init_time,
#             "mock_init_time": self.mock_init_time,
#             "mock_current_time": datetime.now(),  # In real market, mock_current_time is
#             "time_offset": datetime.now() - self.real_init_time,
#             "playback_speed": self.playback_speed,
#             "manual_time_offset": self.manual_time_offset
#         }
