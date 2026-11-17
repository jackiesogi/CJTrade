"""Beginner-friendly API for CJTrade Strategy Editor

This module provides a Pine Script-like experience for users who want to write
trading strategies without worrying about the underlying implementation details.

Examples
--------
    from cjtrade.pkgs.api.beginner import *

    def setup():
        # Optional initialization
        pass

    def strategy(kbar):
        ema = ta.ema(kbar.closes, 12)
        if kbar.close > ema[-1]:
            return buy(qty=100)
        return None

Warnings
--------
Functions share one module-level broker client and current symbol.
`buy` and `sell` can place REAL orders.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Optional

import numpy as np
from cjtrade.pkgs.analytics.technical import ta
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.chart import KbarChartClient
from cjtrade.pkgs.chart import KbarChartType
from cjtrade.pkgs.models import Kbar
from cjtrade.pkgs.models import Order
from cjtrade.pkgs.models import OrderType
from cjtrade.pkgs.models import Position
from cjtrade.pkgs.models import Product
from dotenv import load_dotenv

load_dotenv()

# ============ Global State (Context Management) ============
_global_client: Optional[AccountClient] = None
_current_symbol: Optional[str] = None
_current_position: Optional[Position] = None


@dataclass
class KbarSeries:
    """Beginner-friendly kbar container with vector fields + latest OHLCV shortcuts."""
    symbol: str
    timestamps: list
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray

    @property
    def open(self) -> float:
        """Latest open, or 0.0 if there are no bars."""
        return float(self.opens[-1]) if len(self.opens) else 0.0

    @property
    def high(self) -> float:
        """Latest high, or 0.0 if there are no bars."""
        return float(self.highs[-1]) if len(self.highs) else 0.0

    @property
    def low(self) -> float:
        """Latest low, or 0.0 if there are no bars."""
        return float(self.lows[-1]) if len(self.lows) else 0.0

    @property
    def close(self) -> float:
        """Latest close, or 0.0 if there are no bars."""
        return float(self.closes[-1]) if len(self.closes) else 0.0

    @property
    def volume(self) -> int:
        """Latest volume, or 0 if there are no bars."""
        return int(self.volumes[-1]) if len(self.volumes) else 0


def to_kbar_series(kbars: Optional[list], symbol: str = "") -> Optional[KbarSeries]:
    """Convert a list[Kbar] to KbarSeries used by beginner strategies.

    Returns
    -------
    KbarSeries or None
        `kbars` itself if it already looks like a series; None if `kbars` is
        empty or conversion fails.
    """
    if not kbars:
        return None

    # Already in series-like shape
    if hasattr(kbars, 'closes') and hasattr(kbars, 'close'):
        return kbars

    try:
        return KbarSeries(
            symbol=symbol,
            timestamps=[k.timestamp for k in kbars],
            opens=np.array([k.open for k in kbars], dtype=float),
            highs=np.array([k.high for k in kbars], dtype=float),
            lows=np.array([k.low for k in kbars], dtype=float),
            closes=np.array([k.close for k in kbars], dtype=float),
            volumes=np.array([k.volume for k in kbars], dtype=float),
        )
    except Exception as e:
        print(f"Failed to convert kbars to series: {e}")
        return None


def _get_client() -> AccountClient:
    """Get or create the global client instance"""
    global _global_client
    if _global_client is None:
        _global_client = create_client()
    return _global_client


def set_client(client: AccountClient) -> None:
    """Manually set the global client instance.

    Useful for testing or using pre-configured clients.

    Warnings
    --------
    If `client` is a live broker, later `buy` / `sell` calls place real orders.
    """
    global _global_client
    _global_client = client


def set_current_symbol(symbol: str) -> None:
    """Set the current trading symbol for buy/sell operations."""
    global _current_symbol
    _current_symbol = symbol


def get_current_symbol() -> Optional[str]:
    """Get the current trading symbol."""
    return _current_symbol


# ============ Helper Functions ============
def create_client(
    broker_type: BrokerType = BrokerType.MOCK,
    simulation: bool = False,
) -> AccountClient:
    """Create and connect a broker client with environment config.

    Credentials are read from the ``API_KEY``, ``SECRET_KEY``, ``CA_CERT_PATH``
    and ``CA_PASSWORD`` environment variables (``.env`` is loaded on import).

    Parameters
    ----------
    broker_type : BrokerType
        Which broker to connect to (default: MOCK)
    simulation : bool
        Passed to the broker as ``simulation`` (default: False); for SINOPAC
        this selects the Shioaji sandbox instead of the live account.

    Returns
    -------
    AccountClient
        Connected AccountClient instance

    Examples
    --------
    >>> client = create_client(simulation=True)

    Warnings
    --------
    Connects to the broker over the network. With a live broker and
    ``simulation=False`` the client trades a real account.
    """
    config = {
        'api_key': os.getenv('API_KEY'),
        'secret_key': os.getenv('SECRET_KEY'),
        'ca_path': os.getenv('CA_CERT_PATH'),
        'ca_passwd': os.getenv('CA_PASSWORD'),
        'simulation': simulation,
    }
    client = AccountClient(broker_type, **config)
    client.connect()
    return client


def buy(
    qty: int,
    price: Optional[float] = None,
    symbol: Optional[str] = None,
    intraday_odd: bool = True,
) -> Optional[Order]:
    """Place a buy order.

    Parameters
    ----------
    qty : int
        Quantity to buy
    price : float, optional
        Order price. None is sent to the broker as 0; the Sinopac broker
        places a ROD limit order at the given price.
    symbol : str, optional
        Stock symbol (if None, uses current symbol from context)
    intraday_odd : bool
        Allow intraday odd lots (default: True)

    Returns
    -------
    Order or None
        Order object if successful, None otherwise (the error is printed).

    Raises
    ------
    ValueError
        If no symbol is given and none is set in context.

    Examples
    --------
    >>> buy(qty=100)
    >>> buy(qty=50, price=150.5)  # Buy 50 shares at specific price

    Warnings
    --------
    Places an order through the global client. This is a REAL order if that
    client is a live broker (e.g. SINOPAC with ``simulation=False``, set via
    `set_client` or `create_client`). If no client is set, a MOCK client is
    created on first use.
    """
    symbol = symbol or get_current_symbol()
    if not symbol:
        raise ValueError("No symbol specified. Set symbol via set_current_symbol() or pass it directly.")

    client = _get_client()
    try:
        # AccountClient uses `quantity`; keep backward-compatible fallback.
        try:
            result = client.buy_stock(symbol, quantity=qty, price=price or 0, intraday_odd=intraday_odd)
        except TypeError:
            result = client.buy_stock(symbol, qty=qty, price=price or 0, intraday_odd=intraday_odd)
        return result
    except Exception as e:
        print(f"Buy order failed: {e}")
        return None


def sell(
    qty: int,
    price: Optional[float] = None,
    symbol: Optional[str] = None,
    intraday_odd: bool = True,
) -> Optional[Order]:
    """Place a sell order.

    Parameters
    ----------
    qty : int
        Quantity to sell
    price : float, optional
        Order price. None is sent to the broker as 0; the Sinopac broker
        places a ROD limit order at the given price.
    symbol : str, optional
        Stock symbol (if None, uses current symbol from context)
    intraday_odd : bool
        Allow intraday odd lots (default: True)

    Returns
    -------
    Order or None
        Order object if successful, None otherwise (the error is printed).

    Raises
    ------
    ValueError
        If no symbol is given and none is set in context.

    Examples
    --------
    >>> sell(qty=50)

    Warnings
    --------
    Places an order through the global client. This is a REAL order if that
    client is a live broker (e.g. SINOPAC with ``simulation=False``, set via
    `set_client` or `create_client`). If no client is set, a MOCK client is
    created on first use.
    """
    symbol = symbol or get_current_symbol()
    if not symbol:
        raise ValueError("No symbol specified. Set symbol via set_current_symbol() or pass it directly.")

    client = _get_client()
    try:
        # AccountClient uses `quantity`; keep backward-compatible fallback.
        try:
            result = client.sell_stock(symbol, quantity=qty, price=price or 0, intraday_odd=intraday_odd)
        except TypeError:
            result = client.sell_stock(symbol, qty=qty, price=price or 0, intraday_odd=intraday_odd)
        return result
    except Exception as e:
        print(f"Sell order failed: {e}")
        return None


def get_current_price(symbol: Optional[str] = None) -> Optional[float]:
    """Get the latest price for a symbol.

    Parameters
    ----------
    symbol : str, optional
        Stock symbol (if None, uses current symbol)

    Returns
    -------
    float or None
        Current price (snapshot close) or None if failed

    Raises
    ------
    ValueError
        If no symbol is given and none is set in context.

    Examples
    --------
    >>> price = get_current_price("2330")

    Warnings
    --------
    Queries the broker through the global client (a network call for a live
    broker). Errors are printed and None is returned.
    """
    symbol = symbol or get_current_symbol()
    if not symbol:
        raise ValueError("No symbol specified.")

    client = _get_client()
    try:
        product = Product(symbol=symbol)
        snapshots = client.get_snapshots([product])
        return snapshots[0].close if snapshots else None
    except Exception as e:
        print(f"Failed to get current price: {e}")
        return None


def get_positions() -> list:
    """Get all current positions.

    Returns
    -------
    list of Position
        List of Position objects

    Examples
    --------
    >>> positions = get_positions()
    >>> for pos in positions:
    ...     print(f"{pos.symbol}: {pos.quantity} @ {pos.current_price}")

    Warnings
    --------
    Queries the broker through the global client (a network call for a live
    broker). Errors are printed and an empty list is returned.
    """
    client = _get_client()
    try:
        return client.get_positions()
    except Exception as e:
        print(f"Failed to get positions: {e}")
        return []


def get_balance() -> float:
    """Get current available cash balance.

    Returns
    -------
    float
        Cash balance in TWD

    Examples
    --------
    >>> cash = get_balance()
    >>> print(f"Available cash: {cash}")

    Warnings
    --------
    Queries the broker through the global client (a network call for a live
    broker). Errors are printed and 0.0 is returned.
    """
    client = _get_client()
    try:
        return client.get_balance()
    except Exception as e:
        print(f"Failed to get balance: {e}")
        return 0.0


def get_total_equity() -> float:
    """Get total equity (cash + position values).

    Returns
    -------
    float
        Total equity in TWD

    Warnings
    --------
    Queries the broker through the global client (a network call for a live
    broker). Errors are printed and 0.0 is returned.
    """
    client = _get_client()
    try:
        balance = client.get_balance()
        positions = client.get_positions()
        position_value = sum(p.market_value for p in positions) if positions else 0
        return balance + position_value
    except Exception as e:
        print(f"Failed to get total equity: {e}")
        return 0.0


def get_kbars(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
) -> Optional[list]:
    """Get K-bar data for a symbol in a date range.

    Also sets `symbol` as the current symbol for `buy` / `sell`.

    Parameters
    ----------
    symbol : str
        Stock symbol
    start : str
        Start date (YYYY-MM-DD)
    end : str
        End date (YYYY-MM-DD)
    interval : str
        Time interval (1m, 5m, 15m, 60m, D, etc.)

    Returns
    -------
    list of Kbar or None
        List of Kbar objects or None if failed

    Examples
    --------
    >>> kbars = get_kbars("2330", "2025-01-01", "2025-01-31", "1D")
    >>> for kbar in kbars:
    ...     print(f"{kbar.date}: {kbar.close}")

    Warnings
    --------
    Queries the broker through the global client (a network call for a live
    broker). Errors are printed and None is returned.
    """
    client = _get_client()
    try:
        # Beginner-friendly: remember last queried symbol as context for buy/sell.
        set_current_symbol(symbol)
        product = Product(symbol=symbol)
        return client.get_kbars(product, start, end, interval)
    except Exception as e:
        print(f"Failed to get kbars: {e}")
        return None


def get_kbar_series(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
) -> Optional[KbarSeries]:
    """Fetch kbars and return beginner-friendly KbarSeries.

    Also sets `symbol` as the current symbol, like `get_kbars`.

    Warnings
    --------
    Queries the broker through the global client. Returns None on error.
    """
    raw = get_kbars(symbol=symbol, start=start, end=end, interval=interval)
    return to_kbar_series(raw, symbol=symbol)


# ============ Aliases for brevity ============
# Some users might prefer shorter names
buy_order = buy
sell_order = sell
cash = get_balance
equity = get_total_equity
positions = get_positions
kbars = get_kbars
snapshot_price = get_current_price
to_series = to_kbar_series
series = get_kbar_series


# ============ Public API ============
__all__ = [
    # Core objects (from models and technical analysis)
    'Order', 'OrderType', 'Product', 'Kbar', 'Position',
    'ta',  # Technical analysis namespace

    # Context management
    'set_client', 'set_current_symbol', 'get_current_symbol',
    'create_client',

    # Trading operations
    'buy', 'sell', 'buy_order', 'sell_order',

    # Information queries
    'get_current_price', 'snapshot_price',
    'get_positions', 'positions',
    'get_balance', 'cash',
    'get_total_equity', 'equity',
    'get_kbars', 'kbars',
    'to_kbar_series', 'to_series',
    'get_kbar_series', 'series',
    'KbarSeries',

    # Visualization (optional)
    'KbarChartClient', 'KbarChartType',
]
