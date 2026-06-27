import random
from datetime import datetime
from datetime import timedelta
from time import sleep
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.market_data import ArenaX_Market
from cjtrade.pkgs.brokers.account_client import AccountClient


class ArenaX_Backend_Historical(ArenaX_BackendBase):
    def __init__(
        self,
        state_file: str = "backtest_account_state.json",
        real_account: Optional[AccountClient] = None,
        playback_speed: float = 1.0,
        num_days_preload: int = 3,
        skip_data_preload: bool = False,
        backtest_start_date=None,   # datetime | None; None → random
        **kwargs
    ) -> None:
        super().__init__(
            state_file=state_file,
            real_account=real_account,
            playback_speed=playback_speed,
            num_days_preload=num_days_preload,
            skip_data_preload=skip_data_preload,
        )
        self._backtest_start_date = backtest_start_date
        self.market = ArenaX_Market(real_account=real_account, price_db_path=self.price_db_path)
        if hasattr(self.market, "set_playback_speed"):
            self.market.set_playback_speed(playback_speed)
        self._initialize_market_time()

    def _initialize_market_time(self) -> None:
        if not self.real_account:
            raise ValueError("Historical backend requires a real account to fetch historical data.")

        # ── Fixed start_date path ─────────────────────────────────────
        if self._backtest_start_date is not None:
            start_dt = self._backtest_start_date
            # Skip weekends
            while start_dt.weekday() >= 5:
                start_dt += timedelta(days=1)
            start_dt = start_dt.replace(hour=9, minute=0, second=0, microsecond=0)
            self.market.set_historical_time_abs(
                real_init_time=datetime.now(),
                mock_init_time=start_dt,
            )
            print(f"[ArenaX] Fixed start_date: {start_dt.date()}")
            print(self.market.get_market_time())
            self.market.pause_time_progress()
            print("[ArenaX] Market time paused – waiting for client to call resume.")
            return

        # ── Random start_date path ────────────────────────────────────
        attempt, max_attempts = 0, 30
        days_back = random.randint(self.num_days_preload, 1300)
        dt = datetime.now() - timedelta(days=days_back)
        sleep(1)

        while not self.market.fetching_available(dt) and attempt < max_attempts:
            sleep(0.5)
            attempt += 1
            days_back = random.randint(self.num_days_preload, 1300)
            dt = datetime.now() - timedelta(days=days_back)

        if attempt >= max_attempts:
            print("Not able to fetch historical data within max_attempts. Please try again")
            return
        self.market.set_historical_time(datetime.now(), days_back=days_back)
        print(self.market.get_market_time())
        self.market.pause_time_progress()
        print("[ArenaX] Market time paused – waiting for client to call resume.")
