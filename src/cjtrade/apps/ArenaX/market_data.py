import logging
import os
import random
from datetime import datetime
from datetime import time
from datetime import timedelta
from enum import Enum
from typing import Dict
from typing import List
from typing import Optional

import pandas as pd

log = logging.getLogger("cjtrade.arenax_market")
from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs import paths
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.marketdata import Cached
from cjtrade.pkgs.marketdata import Fallback
from cjtrade.pkgs.marketdata import MarketData
from cjtrade.pkgs.marketdata import PriceCache
from cjtrade.pkgs.marketdata import YFinanceMarketData
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot

def default_market_data(real_account: Optional[AccountClient] = None) -> MarketData:
    """What ArenaX read prices from before sources were pluggable.

    The real account's broker first when there is one, then yfinance.
    """
    if real_account is None:
        return YFinanceMarketData()
    from cjtrade.pkgs.marketdata.sinopac import SinopacMarketData
    return Fallback([SinopacMarketData(real_account), YFinanceMarketData()])


class ArenaX_Market:
    """Simulated exchange clock and historical price cache.

    VOCABULARY
    ----------
    Three separate concepts live here. They used to share the words "system
    time" and "market time" interchangeably, which made the getters look like
    the setters' partners when they were not. Only these three exist:

    1. market time -- what time it is ON THE MARKET right now.
       Read with get_market_time()["mock_current_time"]. Either derived
       (start_date + elapsed * playback_speed + manual_time_offset) or, while
       frozen, read straight back from paused_time.
       Written with set_market_time(t), which also freezes it: a derived value
       cannot be "set" without pinning it, or it would drift away immediately.

    2. timeline origin -- where the simulated timeline BEGINS.
       Held in start_date, reported as mock_init_time.
       Written with set_historical_time_abs() / set_historical_time(), both of
       which snap to 09:00 and may trigger a data preload. Do NOT use either to
       step the clock; see set_market_time().

    3. playback rate and frozen state -- HOW time advances.
       playback_speed (market seconds per real second) plus
       paused / paused_time. Controlled by pause_time_progress() and
       resume_time_progress(); adjust_time() shifts by an offset, and is a no-op
       while frozen because the paused branch of get_market_time() does not read
       manual_time_offset.

    There is deliberately NO "system time" concept. real_current_time and
    real_init_time are this host's wall clock, kept for diagnostics only --
    anything wanting its own machine's clock should call datetime.now() instead,
    since in general the client runs on a different machine.
    """

    def __init__(self, real_account: AccountClient = None,
                 price_db_path: Optional[str] = None,
                 market_data: Optional[MarketData] = None,
                 data: Optional[MarketData] = None):
        """
        Parameters
        ----------
        real_account : AccountClient, optional
            Deprecated as a price source: pass `market_data` instead. Used
            only to build the default source when `market_data` is None.
        price_db_path : str, optional
            The price cache file. Defaults to ``paths.price_db_path()``.
        market_data : MarketData, optional
            Where historical bars come from. Defaults to
            ``default_market_data(real_account)``.
        data : MarketData, optional
            Ready-made cached source, used as is (the backend shares its own).
        """
        self.historical_data = {}     # {symbol: {'data': DataFrame, 'timestamps': numpy_array}}
        self.playback_speed = 1.0     # 1x real-time speed (play N kbars per minute)
        self.real_init_time = 0       # real_current_time - real_init_time = time_offset
        self.mock_init_time = 0       # mock_init_time + time_offset = mock_current_time
        self.start_date = 0
        self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps
        # Pause/resume support
        self.paused: bool = False
        self.paused_time: datetime | None = None

        self.calendar = TradingCalendar()

        self.source = market_data if market_data is not None else default_market_data(real_account)
        self.data = data if data is not None else Cached(self.source, PriceCache(price_db_path))

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

    def fetching_available(self, date: datetime, symbol: str = "2330") -> bool:
        """Return whether 1m bars for `symbol` on `date` are available.

        Asks through the price cache, so a day already on disk counts even
        when the source is offline, and a day fetched here is kept for the
        replay that follows.

        Warnings
        --------
        May make a network call for a day the cache lacks.
        """
        if not self.source.supports("1m"):
            return False
        try:
            return bool(self.data.get_kbars(symbol, date, date + timedelta(days=1), "1m"))
        except Exception as exc:                          # noqa: BLE001
            log.info("probe for %s on %s failed: %s", symbol, date.date(), exc)
            return False


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
            # Was missing, so GET /api/v1/clock always reported
            # paused_time: null even while frozen. mock_current_time already
            # carries the value, so nothing broke -- the field was just dead.
            'paused_time': self.paused_time,
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

    def set_market_time(self, t: datetime) -> datetime:
        """Force logical time to `t` and keep it frozen.

        Unlike pause_time_progress(), this is repeatable: calling it again with a
        later `t` moves frozen time forward. pause_time_progress() returns the
        existing paused_time untouched once self.paused is set, which makes it
        useless as a stepping primitive.

        Unlike set_historical_time_abs(), it does not snap to 09:00, so an
        intraday timestamp survives.

        Used by a replay driver that owns the timeline and advances it
        explicitly instead of deriving it from the wall clock. get_market_time()
        already returns paused_time while paused, so nothing else needs to know.

        Returns the newly frozen mock time.
        """
        self.paused = True
        self.paused_time = t
        return t

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
        session = self.calendar.REGULAR
        market_close_hour = session.close.hour
        market_close_minute = session.close.minute

        current_time_of_day = mock_current_time.time()
        market_open_time = session.open
        market_close_time = session.close

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
        """Is the regular session (一般交易) trading right now?

        Regular lot, not odd lot: callers have no lot to pass and the answer
        has always meant 09:00-13:30. Ask `calendar` directly for a lot-aware
        answer.
        """
        return self.calendar.is_open(
            OrderLot.Common, self.get_market_time()['mock_current_time']
        )

    def create_historical_market(self, symbol: str, days_preload: int = 5):
        """Load `days_preload` days of 1m bars for `symbol` from `start_date`.

        Bars come through the cached source, so windows already in the price
        cache are not fetched again.

        Parameters
        ----------
        symbol : str
            Stock symbol to load data for.
        days_preload : int
            Days after ``start_date`` to load.
        """
        if symbol in self.historical_data:
            return
        end_date = self.start_date + timedelta(days=days_preload)
        try:
            bars = self.data.get_kbars(symbol, self.start_date, end_date, "1m")
        except Exception as exc:                          # noqa: BLE001
            print(f"[{symbol}] Could not load bars: {exc}")
            bars = []
        if not bars:
            self._store_empty_data(symbol, "no bars in the requested window")
            return
        df = pd.DataFrame([{
            'Open': k.open, 'High': k.high, 'Low': k.low,
            'Close': k.close, 'Volume': k.volume,
        } for k in bars], index=[k.timestamp for k in bars])
        self.historical_data[symbol] = {'data': df, 'timestamps': df.index.to_numpy()}
        print(f"[{symbol}] Loaded {len(df)} bar(s) "
              f"({self.start_date.date()} – {end_date.date()}, source={self.source.name})")

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
    """The wall clock and the trading calendar, for backends that trade live.

    Parameters
    ----------
    real_account : AccountClient, optional
        Ignored; kept so existing callers keep working.
    """

    def __init__(self, real_account: Optional[AccountClient] = None):
        self.calendar = TradingCalendar()
        self.playback_speed = 1.0  # Real market doesn't use playback speed, but we keep the attribute for interface consistency
        self.manual_time_offset = timedelta(0)  # Manual time adjustment for time jumps
        self.mock_init_time = datetime.now()  # For real market, mock_init_time is just the time when we start the simulation
        self.real_init_time = datetime.now()  # Real market time baseline

    def is_market_open(self) -> bool:
        """Whether the regular session is open now, by the trading calendar."""
        return self.calendar.is_open(OrderLot.Common, datetime.now())

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
