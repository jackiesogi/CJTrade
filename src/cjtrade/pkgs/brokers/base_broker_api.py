from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict  # noqa: F401  (re-exported; used by importers)
from typing import List

from cjtrade.pkgs.models.kbar import *
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.position import *
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import *
from cjtrade.pkgs.models.trade import Trade

# connect / disconnect / is_connected /
# get_positions / get_balance / get_quotes /
# place_order / get_broker_name
class BrokerAPIBase(ABC):
    """A unified interface for different brokers: accounts and orders.

    Market data is a separate concern (``cjtrade.pkgs.marketdata``).
    ``get_kbars``, ``get_snapshots`` and ``get_bid_ask`` are optional here:
    a broker whose API only places orders leaves them unimplemented, and a
    broker that does serve prices also returns them from ``market_data()``.

    All broker implementations must inherit from
    this class and implement all abstract methods.

    Parameters
    ----------
    **config : Any
        Broker-specific settings, stored as ``self.config``.
    """
    def __init__(self, **config: Any):
        self.config = config

    @abstractmethod
    def connect(self) -> bool:
        """Open the broker session.

        Returns
        -------
        bool
            True if the connection succeeded.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker session."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the broker session is open.

        Returns
        -------
        bool
        """
        pass

    def market_data(self):
        """Return this broker's own MarketData, or None if it serves no prices.

        Returns
        -------
        MarketData or None
            Shares this broker's session.
        """
        return None

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Get current stock positions.

        Returns
        -------
        List[Position]
        """
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """Get account balance.

        Returns
        -------
        float
            Account balance.
        """
        pass

    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        """Return the current bid/ask quote for a product.

        Parameters
        ----------
        product : Product
            The product to quote.
        intraday_odd : bool, optional
            Quote the intraday odd-lot book instead of the board-lot book.

        Returns
        -------
        BidAsk
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not serve market data; "
            "use a cjtrade.pkgs.marketdata.MarketData")

    def get_kbars(self, products: List[Product], start: str, end: str, interval: str) -> List[Kbar]:
        """Return a list of Kbar, 1-min kbar by default.

        Note that the range is [start, end), end is exclusive.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not serve market data; "
            "use a cjtrade.pkgs.marketdata.MarketData")

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        """
        Get real-time market snapshots for given products.
        It must contain more detail than `get_quotes()`/ `get_bid_ask()` does.
        If broker's api does not provide some fields that required by `Snapshot`,
        broker must mention them in the `additional_note`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not serve market data; "
            "use a cjtrade.pkgs.marketdata.MarketData")

    # @abstractmethod  # TODO: Un-comment this when implementation is done
    # Event:
    # - time_period (e.g. every 15 sec)
    # - price_change (e.g. +1% change)
    # - fill_period (e.g. every 100 trade ticks)
    # - volume_thresh (e.g. more than 100 shares traded)
    def register_price_callback():
        """Define what things to do when a certain price event happens.

        Warnings
        --------
        Placeholder: not abstract yet and does nothing.
        """
        pass

    @abstractmethod
    def register_order_callback(self, callback) -> None:
        """Register callback for order status changes (including fills).

        Callback receives OrderEvent with unified CJ abstraction layer format.

        Parameters
        ----------
        callback : callable
            Function that takes OrderEvent as parameter.

        Examples
        --------
        ```python
        def on_order_change(event: OrderEvent):
            print(f"{event.old_status} → {event.new_status}")
            if event.is_filled():
                print(f"Filled: {event.filled_quantity} @ {event.filled_price}")
        ```
        """
        pass

    # @abstractmethod  # TODO: Un-comment this when implementation is done
    def unregister_callback():
        """Unregister a previously registered callback.

        Warnings
        --------
        Placeholder: not abstract yet and does nothing.
        """
        pass

    @abstractmethod
    def place_order(self, order: Order) -> OrderResult:
        """Submit an order to the broker.

        Parameters
        ----------
        order : Order
            The order to place (symbol, action, quantity, price).

        Returns
        -------
        OrderResult

        Warnings
        --------
        On a live broker (Sinopac) this places a real order on a real account.
        """
        pass

    @abstractmethod
    def sync_state(self) -> List[OrderResult]:
        """
        Synchronise the local order state with the broker's backend.

        Replaces the old `commit_order()` whose name was misleading: sinopac has
        no staging area, so `place_order()` submits the order immediately.  What
        the old method really did was call `sj.update_status()` to refresh the
        in-process order map.  `sync_state()` makes that intent explicit.
        """
        pass

    @abstractmethod
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
        On a live broker (Sinopac) this cancels a real order on a real account.
        """
        pass

    @abstractmethod
    def list_orders(self) -> List[Trade]:
        """Return the account's orders.

        Returns
        -------
        List[Trade]
        """
        pass

    @abstractmethod
    def is_market_open(self) -> bool:
        """Return whether the market is open at the broker's market time.

        Returns
        -------
        bool
        """
        pass

    def get_market_time(self) -> dict:
        """What time it is **on the market** right now. Every broker answers this.

        This is the canonical name. "Market time" is the question callers
        actually have -- in a replay it is simulated time, live it is the wall
        clock -- and it matches ArenaX_Market.get_market_time() on the server
        side, so the same words mean the same thing at both ends.

        Required keys:
            mock_current_time   market time now
            real_current_time   the broker host's wall clock, for diagnostics
            mock_init_time      where the simulated timeline starts
            real_init_time      wall clock when that timeline was anchored

        Simulated brokers must also report how their clock is running, so a
        caller can pace itself without reaching into broker internals:
            playback_speed  float  market seconds per real second (1.0 = live)
            paused          bool   True when the clock is frozen

        A live broker reports mock == real, playback_speed=1.0 and paused=False:
        real time is the degenerate case of the same contract, so callers never
        branch on the broker name.

        Note there is deliberately no "system time" concept: the broker host's
        clock is just the real_* fields above, and a caller wanting its own
        machine's clock should call datetime.now() rather than ask the broker --
        the two are different machines in general.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_market_time()"
        )

    def get_system_time(self) -> dict:
        """Deprecated alias for get_market_time(). Prefer get_market_time().

        Kept because "system time" was the original name here, but it reads as
        the setter-partner of set_timeline_origin() -- which writes the timeline
        origin, not the current moment -- and that false pairing is what made
        the two easy to confuse.
        """
        return self.get_market_time()

    @abstractmethod
    def get_broker_name(self) -> str:
        """Return a short name identifying the broker."""
        pass

    ##### SIMPLE HIGH-LEVEL METHODS #####
    @abstractmethod
    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                  opt_field: dict = None) -> OrderResult:
        """Place a buy order for a stock.

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
        On a live broker (Sinopac) this places a real order on a real account.
        """
        pass

    @abstractmethod
    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True,
                   opt_field: dict = None) -> OrderResult:
        """Place a sell order for a stock.

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
        On a live broker (Sinopac) this places a real order on a real account.
        """
        pass
