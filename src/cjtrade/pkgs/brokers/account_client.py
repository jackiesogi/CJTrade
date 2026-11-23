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
from cjtrade.pkgs.utils.extras import missing_extra


class BrokerType(Enum):
    """Supported broker backends.

    Warnings
    --------
    YUANTA and CATHAY are not implemented; AccountClient raises
    NotImplementedError for them. MOCK is the legacy simulated broker.
    """
    SINOPAC = "sinopac"  # 永豐金
    YUANTA  = "yuanta"   # 元大
    CATHAY  = "cathay"   # 國泰
    MOCK    = "mock"     # 模擬券商
    ARENAX  = "arenax"   # 模擬券商 (新)

class AccountState:
    """Account data cached locally by AccountClient.

    Warnings
    --------
    ``pending_orders`` and ``order_history`` are never filled yet.
    """
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
    """One account at one broker: balance, positions and orders.

    Prices are a separate concern. ``client.market`` is the MarketData to
    read them from: the one passed as `market`, or else the broker's own
    (Sinopac and ArenaX serve prices; a broker that only takes orders does
    not, and then `market` is required for anything price-related).

    Parameters
    ----------
    broker_type : BrokerType
        Which broker implementation to use.
    market : MarketData, optional
        Where prices come from. Defaults to the broker's own market data.
    **config
        Passed unchanged to the broker API constructor.

    Raises
    ------
    ImportError
        BrokerType.SINOPAC is chosen but the ``sinopac`` extra is not installed.
    NotImplementedError
        BrokerType.YUANTA or BrokerType.CATHAY is chosen.
    ValueError
        The broker type is not supported.
    """

    def __init__(self, broker_type: BrokerType, market=None, **config):
        self.broker_type = broker_type
        self.broker_api = self._set_broker_api(broker_type, **config)
        self._market = market
        self.account_state = AccountState()
        self.broker_api_conn_keepalive = True  # For future use

    def _set_broker_api(self, broker_type: BrokerType, **config) -> BrokerAPIBase:
        if broker_type == BrokerType.SINOPAC:
            try:
                from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
            except ImportError as e:
                raise missing_extra("sinopac", e) from e
            return SinopacBrokerAPI(**config)
        elif broker_type in (BrokerType.YUANTA, BrokerType.CATHAY):
            raise NotImplementedError(
                f"The {broker_type.value} broker is not implemented yet")
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

    @property
    def market(self):
        """The MarketData prices come from, or None if there is none.

        Returns
        -------
        MarketData or None
            The one given to the constructor, else the broker's own.
        """
        if self._market is None:
            self._market = self.broker_api.market_data()
        return self._market

    def _explicit_market(self):
        """The MarketData passed in, if any. Data shims route through it."""
        return self._market if self._market is not None and \
            not self._market_is_brokers() else None

    def _market_is_brokers(self) -> bool:
        return getattr(self._market, "broker", None) is self.broker_api

    # User need to call `connect()` before calling any other method
    def connect(self) -> bool:
        """Connect to the broker. Call this before any other method.

        Returns
        -------
        bool
            True if the connection succeeded.

        Warnings
        --------
        Makes a network call to the broker.
        """
        return self.broker_api.connect()

    def disconnect(self) -> None:
        """Disconnect from the broker.

        Warnings
        --------
        Makes a network call to the broker.
        """
        self.broker_api.disconnect()

    def is_connected(self) -> bool:
        """Return whether the broker session is open.

        Returns
        -------
        bool
        """
        return self.broker_api.is_connected()

    def get_positions(self) -> List[Position]:
        """Sync with the broker and return current positions.

        Returns
        -------
        List[Position]

        Warnings
        --------
        Runs a full sync (network calls for balance and positions) on every call.
        If not connected, it prints a message and returns the cached value.
        """
        self._sync_all()  # will sync `account_state`
        return self.account_state.positions

    def get_balance(self) -> float:
        """Sync with the broker and return the account balance.

        Returns
        -------
        float

        Warnings
        --------
        Runs a full sync (network calls for balance and positions) on every call.
        If not connected, it prints a message and returns the cached value.
        """
        self._sync_all()  # will sync `account_state`
        return self.account_state.balance

    def get_account_state(self) -> AccountState:
        """Balance and positions from a single sync.

        get_balance() and get_positions() each run a full `_sync_all()`, so
        asking for both costs two syncs and returns two views of the account
        taken a round-trip apart. A caller that needs them together -- anything
        reporting "here is your new balance and your new position" -- wants one
        consistent read, not two.

        Warnings
        --------
        Makes network calls to the broker. If not connected, it prints a
        message and returns the cached state.
        """
        self._sync_all()  # will sync `account_state`
        return self.account_state

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, float]:
        """Return the current bid/ask quote for a product.

        Prefer ``client.market``; this stays for existing callers. With a
        `market` passed to the constructor it reads from that, otherwise from
        the broker as before.

        Parameters
        ----------
        product : Product
            The product to quote.
        intraday_odd : bool, optional
            Quote the intraday odd-lot book instead of the board-lot book.

        Returns
        -------
        BidAsk or None
            Sinopac returns None if no quote arrives within 5 seconds.

        Warnings
        --------
        Makes a network call. On ArenaX the levels are simulated around the
        last close with random volumes, not real quotes.
        """
        market = self._explicit_market()
        if market is not None:
            return market.get_bid_ask(product.symbol, intraday_odd)
        return self.broker_api.get_bid_ask(product, intraday_odd)

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """Return market snapshots for the given products.

        Prefer ``client.market``; this stays for existing callers. With a
        `market` passed to the constructor it reads from that, otherwise from
        the broker as before.

        Parameters
        ----------
        products : List[Product]

        Returns
        -------
        List[Snapshot]

        Warnings
        --------
        Makes a network call to the broker.
        """
        market = self._explicit_market()
        if market is not None:
            return market.get_snapshots([p.symbol for p in products])
        return self.broker_api.get_snapshots(products)

    def register_order_callback(self, callback: OrderCallback) -> None:
        """Register callback for order status changes (including fills).

        Parameters
        ----------
        callback : OrderCallback
            Function(OrderEvent) -> None.

        Examples
        --------
        ```python
        def on_order_change(event: OrderEvent):
            print(f"{event.old_status} → {event.new_status}")
            if event.is_filled():
                # Handle fill
                update_position(event.symbol, event.filled_quantity)
        ```

        Warnings
        --------
        ArenaX raises NotImplementedError; poll sync_state() or list_orders() there.
        """
        return self.broker_api.register_order_callback(callback)

    def get_kbars(self, product: Product, start: str, end: str, interval: str):
        """Return kbars for a product over [start, end); end is exclusive.

        Prefer ``client.market``; this stays for existing callers. With a
        `market` passed to the constructor it reads from that, otherwise from
        the broker as before.

        Parameters
        ----------
        product : Product
            The product to fetch.
        start : str
            Start date.
        end : str
            End date, exclusive.
        interval : str
            One of '1m', '3m', '5m', '10m', '15m', '20m', '30m', '45m',
            '1h', '90m', '2h', '1d', '1w', '1M'. Support depends on the broker.

        Returns
        -------
        List[Kbar]

        Warnings
        --------
        Makes a network call to the broker.
        """
        # note that the range is [start,end), end is exclusive.
        # TODO: test each interval aggregation stability (especially edge cases)
        # interval: '1m', '3m', '5m', '10m', '15m', '20m', '30m', '45m',
        #           '1h', '90m', '2h', '1d', '1w', '1M'
        market = self._explicit_market()
        if market is not None:
            return market.get_kbars(product.symbol, start, end, interval)
        return self.broker_api.get_kbars(product, start, end, interval)

    def get_market_movers(self, top_n: int = 10, by: RankType = RankType.PRICE_PERCENTAGE_CHANGE, ascending: bool = True) -> Dict[str, float]:
        """Return the top movers ranked by `by`.

        Parameters
        ----------
        top_n : int, optional
            Number of products to return.
        by : RankType, optional
            Ranking criterion.
        ascending : bool, optional
            Sort order.

        Returns
        -------
        dict or None
            Sinopac maps product name to Snapshot; ArenaX returns None.

        Warnings
        --------
        Makes a network call. Not implemented on ArenaX.
        """
        return self.broker_api.get_market_movers(top_n, by, ascending)

    def place_order(self, order: Order) -> OrderResult:
        """Place an order.

        Parameters
        ----------
        order : Order

        Returns
        -------
        OrderResult

        Warnings
        --------
        With BrokerType.SINOPAC this places a REAL order on a real account.
        """
        return self.broker_api.place_order(order)

    def sync_state(self) -> List[OrderResult]:
        """Refresh order status from the broker.

        Returns
        -------
        List[OrderResult]

        Warnings
        --------
        Makes network calls. ArenaX and Sinopac write order status to the local
        mirror database.
        """
        return self.broker_api.sync_state()

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order.

        Parameters
        ----------
        order_id : str
            The CJTrade order id.

        Returns
        -------
        OrderResult

        Warnings
        --------
        With BrokerType.SINOPAC this cancels a REAL order on a real account.
        """
        return self.broker_api.cancel_order(order_id)

    def list_orders(self) -> List[Trade]:
        """Return the account's orders.

        Returns
        -------
        List[Trade]

        Warnings
        --------
        Makes a network call to the broker.
        """
        # Trade, not Dict: both implementations (arenax, sinopac) already return
        # Trade objects, and the annotation saying otherwise is what pushes
        # callers into subscripting them.
        return self.broker_api.list_orders()

    def is_market_open(self) -> bool:
        """Return whether the market is open.

        Returns
        -------
        bool

        Warnings
        --------
        Sinopac checks the local wall clock; ArenaX checks the server's market
        time. Both use weekdays 09:00-13:30 only and ignore holidays.
        """
        return self.broker_api.is_market_open()

    def get_market_time(self) -> dict:
        """What time it is on the market now. Same keys for every broker.

        See BrokerAPIBase.get_market_time for the key list. Includes
        playback_speed and paused, so a caller can pace itself against a
        simulated clock without knowing which broker it is talking to; a live
        broker reports 1.0 / False.

        Warnings
        --------
        Result depends on the current time. ArenaX makes a network call.
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

        Warnings
        --------
        Calls get_market_time() each time; on ArenaX that is a network call.
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
        """Return a short name identifying the broker."""
        return self.broker_api.get_broker_name()

    @property
    def current_broker_type(self) -> BrokerType:
        """The BrokerType this client was created with."""
        return self.broker_type

    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
        """Place a limit buy order for a stock.

        Parameters
        ----------
        symbol : str
            Stock symbol, e.g. ``'2330'``.
        quantity : int
            Order quantity.
        price : float
            Limit price.
        intraday_odd : bool, optional
            True for an intraday odd-lot order, False for a board-lot order.
        opt_field : dict, optional
            Extra fields attached to the order.

        Returns
        -------
        OrderResult

        Warnings
        --------
        With BrokerType.SINOPAC this places a REAL order on a real account.
        """
        return self.broker_api.buy_stock(symbol, quantity, price, intraday_odd, opt_field=opt_field)

    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
        """Place a limit sell order for a stock.

        Parameters
        ----------
        symbol : str
            Stock symbol, e.g. ``'2330'``.
        quantity : int
            Order quantity.
        price : float
            Limit price.
        intraday_odd : bool, optional
            True for an intraday odd-lot order, False for a board-lot order.
        opt_field : dict, optional
            Extra fields attached to the order.

        Returns
        -------
        OrderResult

        Warnings
        --------
        With BrokerType.SINOPAC this places a REAL order on a real account.
        """
        return self.broker_api.sell_stock(symbol, quantity, price, intraday_odd, opt_field=opt_field)
