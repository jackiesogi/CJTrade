"""
Beginner-friendly API for CJTrade Strategy Editor

This module provides a Pine Script-like experience for users who want to write
trading strategies without worrying about the underlying implementation details.

Example:
    from cjtrade.pkgs.api.beginner import *

    def setup():
        # Optional initialization
        pass

    def strategy(kbar):
        ema = ta.ema(kbar.closes, 12)
        if kbar.close > ema[-1]:
            return buy(qty=100)
        return None
"""
import os
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Optional

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


def _get_client() -> AccountClient:
    """Get or create the global client instance"""
    global _global_client
    if _global_client is None:
        _global_client = create_client()
    return _global_client


def set_client(client: AccountClient) -> None:
    """
    Manually set the global client instance.
    Useful for testing or using pre-configured clients.
    """
    global _global_client
    _global_client = client


def set_current_symbol(symbol: str) -> None:
    """Set the current trading symbol for buy/sell operations"""
    global _current_symbol
    _current_symbol = symbol


def get_current_symbol() -> Optional[str]:
    """Get the current trading symbol"""
    return _current_symbol


# ============ Helper Functions ============
def create_client(
    broker_type: BrokerType = BrokerType.SINOPAC,
    simulation: bool = False,
) -> AccountClient:
    """
    Create and connect a broker client with environment config.

    Args:
        broker_type: Which broker to connect to (default: SINOPAC)
        simulation: Whether to use mock broker (default: False)

    Returns:
        Connected AccountClient instance

    Example:
        client = create_client(simulation=True)  # Use mock broker
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
    """
    Place a buy order.

    Args:
        qty: Quantity to buy
        price: Order price (if None, uses market price)
        symbol: Stock symbol (if None, uses current symbol from context)
        intraday_odd: Allow intraday odd lots (default: True)

    Returns:
        Order object if successful, None otherwise

    Example:
        buy(qty=100)  # Buy 100 shares at market price
        buy(qty=50, price=150.5)  # Buy 50 shares at specific price
    """
    symbol = symbol or get_current_symbol()
    if not symbol:
        raise ValueError("No symbol specified. Set symbol via set_current_symbol() or pass it directly.")

    client = _get_client()
    try:
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
    """
    Place a sell order.

    Args:
        qty: Quantity to sell
        price: Order price (if None, uses market price)
        symbol: Stock symbol (if None, uses current symbol from context)
        intraday_odd: Allow intraday odd lots (default: True)

    Returns:
        Order object if successful, None otherwise

    Example:
        sell(qty=50)  # Sell 50 shares at market price
    """
    symbol = symbol or get_current_symbol()
    if not symbol:
        raise ValueError("No symbol specified. Set symbol via set_current_symbol() or pass it directly.")

    client = _get_client()
    try:
        result = client.sell_stock(symbol, qty=qty, price=price or 0, intraday_odd=intraday_odd)
        return result
    except Exception as e:
        print(f"Sell order failed: {e}")
        return None


def get_current_price(symbol: Optional[str] = None) -> Optional[float]:
    """
    Get the latest price for a symbol.

    Args:
        symbol: Stock symbol (if None, uses current symbol)

    Returns:
        Current price or None if failed

    Example:
        price = get_current_price("2330")
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
    """
    Get all current positions.

    Returns:
        List of Position objects

    Example:
        positions = get_positions()
        for pos in positions:
            print(f"{pos.symbol}: {pos.quantity} @ {pos.current_price}")
    """
    client = _get_client()
    try:
        return client.get_positions()
    except Exception as e:
        print(f"Failed to get positions: {e}")
        return []


def get_balance() -> float:
    """
    Get current available cash balance.

    Returns:
        Cash balance in TWD

    Example:
        cash = get_balance()
        print(f"Available cash: {cash}")
    """
    client = _get_client()
    try:
        return client.get_balance()
    except Exception as e:
        print(f"Failed to get balance: {e}")
        return 0.0


def get_total_equity() -> float:
    """
    Get total equity (cash + position values).

    Returns:
        Total equity in TWD
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
    interval: str = "1m",
) -> Optional[list]:
    """
    Get K-bar data for a symbol in a date range.

    Args:
        symbol: Stock symbol
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        interval: Time interval (1m, 5m, 15m, 60m, D, etc.)

    Returns:
        List of Kbar objects or None if failed

    Example:
        kbars = get_kbars("2330", "2025-01-01", "2025-01-31", "1D")
        for kbar in kbars:
            print(f"{kbar.date}: {kbar.close}")
    """
    client = _get_client()
    try:
        product = Product(symbol=symbol)
        return client.get_kbars(product, start, end, interval)
    except Exception as e:
        print(f"Failed to get kbars: {e}")
        return None


# ============ Aliases for brevity ============
# Some users might prefer shorter names
buy_order = buy
sell_order = sell
cash = get_balance
equity = get_total_equity
positions = get_positions
kbars = get_kbars
snapshot_price = get_current_price


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

    # Visualization (optional)
    'KbarChartClient', 'KbarChartType',
]
