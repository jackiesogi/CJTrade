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
        state_file: str = "mock_account_state.json",
        real_account: Optional[AccountClient] = None,
        playback_speed: float = 1.0,
        num_days_preload: int = 3,
        skip_data_preload: bool = False,
        **kwargs
    ) -> None:
        super().__init__(
            state_file=state_file,
            real_account=real_account,
            playback_speed=playback_speed,
            num_days_preload=num_days_preload,
            skip_data_preload=skip_data_preload,
        )
        self.market = ArenaX_Market(real_account=real_account)
        if hasattr(self.market, "set_playback_speed"):
            self.market.set_playback_speed(playback_speed)
        self._initialize_market_time()

    def _initialize_market_time(self) -> None:
        attempt, max_attempts = 0, 30
        days_back = random.randint(self.num_days_preload, 20)
        if self.real_account:
            days_back = random.randint(self.num_days_preload, 1300)

        dt = datetime.now() - timedelta(days=days_back)
        sleep(1)

        while not self.market.fetching_available(dt) and attempt < max_attempts:
            sleep(0.5)
            attempt += 1
            days_back = random.randint(self.num_days_preload, 20)
            dt = datetime.now() - timedelta(days=days_back)

        if attempt >= max_attempts:
            print("Not able to fetch historical data within max_attempts. Please try again")
            return
        self.market.set_historical_time(datetime.now(), days_back=days_back)
        print(self.market.get_market_time())
