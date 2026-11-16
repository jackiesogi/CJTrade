import uuid
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

from cjtrade.pkgs.brokers.base_broker_api import *
from cjtrade.pkgs.models.event import *
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.position import *
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import *
from cjtrade.pkgs.models.rank_type import *
from cjtrade.pkgs.models.trade import Trade


class BrokerType(Enum):
    SINOPAC = "sinopac"  # 永豐金
    YUANTA  = "yuanta"   # 元大
    CATHAY  = "cathay"   # 國泰
    MOCK    = "mock"     # 模擬券商
    ARENAX  = "arenax"   # 模擬券商 (新)

class AccountState:
    def __init__(self):
        self.positions: List[Position] = []
        self.balance: float = 0.0
        self.last_sync_time: str = ""
        self.pending_orders: List[Order] = [] # Don't implement it for now, too complex.
        self.order_history: List[Order] = []  # Don't implement it for now, too complex.


# AccountClient = Broker's API (sync source) + AccountState (local cached state)
# For example, when user try to access account balance, AccountClient will:
#   1. Call BrokerAPI to sync the latest state from remote broker server
#   2. Update AccountState with the latest data
#   3. Return the cached balance from AccountState
# TODO: support the context manager protocol (with AccountClient() as account:)
class AccountClient:
    """An unified API to interact with different brokers."""

    def __init__(self, broker_type: BrokerType, **config):
        self.broker_type = broker_type
        self.broker_api = self._set_broker_api(broker_type, **config)
        self.account_state = AccountState()
        self.broker_api_conn_keepalive = True  # For future use

    def _set_broker_api(self, broker_type: BrokerType, **config) -> BrokerAPIBase:
        if broker_type == BrokerType.SINOPAC:
            from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
            return SinopacBrokerAPI(**config)
        elif broker_type == BrokerType.YUANTA:
            from cjtrade.pkgs.brokers.yuanta.yuanta import YuantaBrokerAPI
            return YuantaBrokerAPI(**config)
        elif broker_type == BrokerType.CATHAY:
            from cjtrade.pkgs.brokers.cathay.cathay import CathayBrokerAPI
            return CathayBrokerAPI(**config)
        elif broker_type == BrokerType.MOCK:
            from cjtrade.pkgs.brokers.arenax.legacy.mock_broker_api import MockBrokerAPI
            return MockBrokerAPI(**config)
        elif broker_type == BrokerType.ARENAX:
            # User can set their `real_account` backend (for price feed) via tweaking
            # configurations in ArenaX Brokerside Server and Backend.
            # This is the server's business, not the client's. (`AccountClient` just acts as a pure client)
            from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
            return ArenaXBrokerAPI_v2(**config)
        else:
            raise ValueError(f"Unsupported broker type: {broker_type}")

    def _sync_all(self) -> bool:
        if not self.broker_api.is_connected():
            print("Broker API not connected")
            return False
        self.account_state.balance = self.broker_api.get_balance()
        self.account_state.positions = self.broker_api.get_positions()
        self.account_state.last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # self.account_state.pending_orders = self.broker_api.list_orders()
        # self.account_state.order_history = []

    # User need to call `connect()` before calling any other method
    def connect(self) -> bool:
        return self.broker_api.connect()

    def disconnect(self) -> None:
        self.broker_api.disconnect()

    def is_connected(self) -> bool:
        return self.broker_api.is_connected()

    def get_positions(self) -> List[Position]:
        self._sync_all()  # will sync `account_state`
        return self.account_state.positions

    def get_balance(self) -> float:
        self._sync_all()  # will sync `account_state`
        return self.account_state.balance

    def get_account_state(self) -> AccountState:
        """Balance and positions from a single sync.

        get_balance() and get_positions() each run a full `_sync_all()`, so
        asking for both costs two syncs and returns two views of the account
        taken a round-trip apart. A caller that needs them together -- anything
        reporting "here is your new balance and your new position" -- wants one
        consistent read, not two.
        """
        self._sync_all()  # will sync `account_state`
        return self.account_state

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, float]:
        return self.broker_api.get_bid_ask(product, intraday_odd)

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        return self.broker_api.get_snapshots(products)

    def register_order_callback(self, callback: OrderCallback) -> None:
        """
        Register callback for order status changes (including fills).

        Args:
            callback: Function(OrderEvent) -> None

        Example:
            def on_order_change(event: OrderEvent):
                print(f"{event.old_status} → {event.new_status}")
                if event.is_filled():
                    # Handle fill
                    update_position(event.symbol, event.filled_quantity)
        """
        return self.broker_api.register_order_callback(callback)

    def get_kbars(self, product: Product, start: str, end: str, interval: str):
        # note that the range is [start,end), end is exclusive.
        # TODO: test each interval aggregation stability (especially edge cases)
        # interval: '1m', '3m', '5m', '10m', '15m', '20m', '30m', '45m',
        #           '1h', '90m', '2h', '1d', '1w', '1M'
        return self.broker_api.get_kbars(product, start, end, interval)

    def get_market_movers(self, top_n: int = 10, by: RankType = RankType.PRICE_PERCENTAGE_CHANGE, ascending: bool = True) -> Dict[str, float]:
        return self.broker_api.get_market_movers(top_n, by, ascending)

    def place_order(self, order: Order) -> OrderResult:
        return self.broker_api.place_order(order)

    def sync_state(self) -> List[OrderResult]:
        return self.broker_api.sync_state()

    def cancel_order(self, order_id: str) -> OrderResult:
        return self.broker_api.cancel_order(order_id)

    def list_orders(self) -> List[Trade]:
        # Trade, not Dict: both implementations (arenax, sinopac) already return
        # Trade objects, and the annotation saying otherwise is what pushes
        # callers into subscripting them.
        return self.broker_api.list_orders()

    def is_market_open(self) -> bool:
        return self.broker_api.is_market_open()

    def get_market_time(self) -> dict:
        """What time it is on the market now. Same keys for every broker.

        See BrokerAPIBase.get_market_time for the key list. Includes
        playback_speed and paused, so a caller can pace itself against a
        simulated clock without knowing which broker it is talking to; a live
        broker reports 1.0 / False.
        """
        return self.broker_api.get_market_time()

    def get_system_time(self) -> dict:
        """Deprecated alias for get_market_time()."""
        return self.get_market_time()

    @property
    def playback_speed(self) -> float:
        """Market seconds per real second. 1.0 for any live broker.

        Use this to scale your own waiting, e.g. sleep(seconds / speed), rather
        than configuring the speed separately on both sides: the broker is the
        authority on how fast its own clock runs, so asking it is the only way
        the two cannot disagree.
        """
        return float(self.get_market_time().get("playback_speed", 1.0))

    @property
    def control_plane(self):
        """Broker-server control plane, or None when there is nothing to control.

        Not named `simulation`: that word is already taken in this codebase for
        Shioaji's sandbox flag (SIMULATION=y -> SinopacBrokerAPI.simulation), and
        the two are unrelated — a sinopac sandbox account is still a live broker
        with no clock to steer.

        Deliberately NOT part of BrokerAPIBase either: freezing a clock, stepping
        a replay or restarting a backend are things only a simulated exchange can
        do, and declaring them there would force every adapter (yuanta, cathay,
        IBKR) to implement methods that have no meaning for a real broker.

        It lives here so callers never reach through
        `client.broker_api.middleware`. Against a real broker it is None, which
        is an explicit check rather than an AttributeError two layers down.

        Example::

            if client.control_plane:
                client.control_plane.resume_time_progress()
        """
        return getattr(self.broker_api, "middleware", None)

    def get_broker_name(self) -> str:
        return self.broker_api.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        return self.broker_type

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
        return self.broker_api.buy_stock(symbol, quantity, price, intraday_odd, opt_field=opt_field)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
        return self.broker_api.sell_stock(symbol, quantity, price, intraday_odd, opt_field=opt_field)
