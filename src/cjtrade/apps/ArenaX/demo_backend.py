import random
from datetime import datetime
from datetime import timedelta
from time import sleep
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.market_data import ArenaX_Market
from cjtrade.pkgs.brokers.account_client import AccountClient


# Upper bound on how far back the simulated "now" is placed. Roughly the 1m
# history a free data source will serve, which is all this backend has.
_MAX_DAYS_BACK = 20


class ArenaX_Backend_None(ArenaX_BackendBase):
	def __init__(
		self,
		state_file: Optional[str] = None,   # snapshot to resume from; None = fresh
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
			**kwargs
		)
		self.market = ArenaX_Market(real_account=None, price_db_path=self.price_db_path)
		if hasattr(self.market, "set_playback_speed"):
			self.market.set_playback_speed(playback_speed)
		self._initialize_market_time()

	def _random_days_back(self) -> int:
		"""How far back to put the simulated "now".

		At least `num_days_preload`, so the preload window fits inside data
		that already exists rather than running off the end of it, and no
		further than _MAX_DAYS_BACK, which is roughly how much 1m history a
		free source will serve.

		The bounds can conflict: ask for a 300-day preload and there is no
		value that is both >= 300 and <= 20. Honour the preload and say so --
		`random.randint(300, 20)` raised ValueError out of __init__, so the
		whole server failed to start for any AX_BACKTEST_DURATION_DAYS above
		20, with the shipped 11 sitting just inside the limit.
		"""
		lo = max(int(self.num_days_preload), 1)
		if lo > _MAX_DAYS_BACK:
			return lo
		return random.randint(lo, _MAX_DAYS_BACK)

	def _initialize_market_time(self) -> None:
		attempt, max_attempts = 0, 30
		days_back = self._random_days_back()
		dt = datetime.now() - timedelta(days=days_back)
		sleep(1)

		while not self.market.fetching_available(dt) and attempt < max_attempts:
			sleep(0.5)
			attempt += 1
			days_back = self._random_days_back()
			dt = datetime.now() - timedelta(days=days_back)

		if attempt >= max_attempts:
			print("Not able to fetch historical data within max_attempts. Please try again")
			return
		self.market.set_historical_time(datetime.now(), days_back=days_back)
		print(self.market.get_market_time())
        # Pause immediately so client initialisation lag does not consume mock time.
        # Client must call PATCH /api/v1/clock {"paused": false} once ready.
		# self.market.pause_time_progress()
		# print("[ArenaX] Market time paused – waiting for client to call resume.")
