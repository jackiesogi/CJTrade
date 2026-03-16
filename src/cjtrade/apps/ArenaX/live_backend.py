from typing import Dict
from typing import List
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.market_data import ArenaX_Market
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models.kbar import Kbar


class ArenaX_Backend_PaperTrade(ArenaX_BackendBase):
	def __init__(
		self,
		state_file: str = "mock_account_state.json",
		real_account: Optional[AccountClient] = None,
		playback_speed: float = 1.0,
	) -> None:
		super().__init__(
			state_file=state_file,
			real_account=real_account,
			playback_speed=playback_speed,
			num_days_preload=0,
			skip_data_preload=True,
		)
		self.market = ArenaX_Market(real_account=real_account)
		if hasattr(self.market, "set_playback_speed"):
			self.market.set_playback_speed(playback_speed)
		if self.real_account and not self.real_account.is_connected():
			self.real_account.connect()
		self._kbar_buffer: Dict[str, List[Kbar]] = {}
