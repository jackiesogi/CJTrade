"""
pkgs/strategy/base_strategy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract base class for all CJTrade strategies.

Both the time-progression runner (cjtrade_system_arenax.py) and the
one-shot backtest engine (cjtrade_oneshot_backtest.py) drive strategies
through the same interface, so a strategy written once works in both modes.

Lifecycle
---------
    on_start(context)                  ← called once before the first bar
    for each bar:
        on_bar(bar, context) → List[Signal]
    on_fill(fill, context)             ← called after each simulated fill
    on_end(context)                    ← called once after the last bar

Signal types
------------
    Signal(action='BUY'|'SELL'|'HOLD', symbol, quantity, price, reason)

Example
-------
    class MyStrategy(BaseStrategy):
        def on_bar(self, bar, ctx):
            if bar.close < ctx.lower_bb(bar.symbol):
                return [Signal('BUY', bar.symbol, ctx.calc_qty(bar.close), bar.close)]
            return []
"""
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


# ---------------------------------------------------------------------------
# Signal – what a strategy emits each bar
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A trade signal produced by a strategy on a given bar.

    Attributes
    ----------
    action : str
        'BUY', 'SELL', or 'HOLD' (HOLD is a no-op, mostly for logging).
    symbol : str
        Stock ticker, e.g. '2330'.
    quantity : int
        Number of lots (張).  Must be > 0 for BUY/SELL.
    price : float
        Limit price to submit.
    reason : str, optional
        Human-readable explanation (appears in logs / fill_history).
    meta : dict, optional
        Arbitrary extra data (e.g. indicator values at signal time).
    """
    action: str          # 'BUY' | 'SELL' | 'HOLD'
    symbol: str
    quantity: int
    price: float
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# StrategyContext – read-only view of account state passed to the strategy
# ---------------------------------------------------------------------------

@dataclass
class StrategyContext:
    """Snapshot of account state visible to the strategy at each bar.

    The engine populates this before calling on_bar() so the strategy
    never has to call the broker API directly.

    Attributes
    ----------
    timestamp : datetime
        Mock/real time of the current bar.
    balance : float
        Available cash.
    equity : float
        balance + total market value of all open positions.
    positions : list[dict]
        Each dict: {'symbol', 'quantity', 'avg_cost', 'current_price',
                    'market_value', 'unrealized_pnl'}
    price_history : dict[symbol, list[float]]
        Close prices seen so far (most-recent last).
    bar_index : int
        0-based index of the current bar within the full kbar list.
    params : dict
        Strategy-specific parameters forwarded from the runner config.
    """
    timestamp: datetime
    balance: float
    equity: float
    positions: List[Dict]
    price_history: Dict[str, List[float]]
    bar_index: int = 0
    params: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def has_position(self, symbol: str) -> bool:
        return any(p["symbol"] == symbol and p["quantity"] > 0
                   for p in self.positions)

    def position_qty(self, symbol: str) -> int:
        for p in self.positions:
            if p["symbol"] == symbol:
                return p["quantity"]
        return 0

    def calc_qty(self, price: float, max_pct: float = 0.05) -> int:
        """Return lot count that keeps position ≤ max_pct of current equity."""
        if price <= 0 or self.equity <= 0:
            return 0
        max_value = self.equity * max_pct
        qty = int(max_value / price)
        return max(qty, 1) if self.balance >= price else 0

    def prices(self, symbol: str) -> List[float]:
        """Shorthand for price_history[symbol] (returns [] if not found)."""
        return self.price_history.get(symbol, [])


# ---------------------------------------------------------------------------
# Fill – what the engine reports back after execution
# ---------------------------------------------------------------------------

@dataclass
class Fill:
    """Represents an executed trade returned to on_fill()."""
    symbol: str
    action: str          # 'BUY' | 'SELL'
    quantity: int
    price: float
    timestamp: datetime
    commission: float = 0.0
    reason: str = ""


# ---------------------------------------------------------------------------
# BaseStrategy – abstract base class
# ---------------------------------------------------------------------------

class BaseStrategy(ABC):
    """All strategies must subclass this and implement on_bar().

    The engine calls the lifecycle hooks in order:
        on_start → [on_bar → on_fill*] × N → on_end
    """

    # Optional display name (used in reports)
    name: str = "UnnamedStrategy"

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_start(self, ctx: StrategyContext) -> None:
        """Called once before the first bar.  Override for initialisation."""
        pass

    @abstractmethod
    def on_bar(self, bar: Any, ctx: StrategyContext) -> List[Signal]:
        """Process one Kbar and return a list of Signals (may be empty).

        Parameters
        ----------
        bar : Kbar
            The current bar (open, high, low, close, volume, timestamp).
        ctx : StrategyContext
            Current account state and price history.

        Returns
        -------
        list[Signal]
            Zero or more signals.  HOLD signals are logged but not traded.
        """
        ...

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Called after every simulated fill.  Override to track state."""
        pass

    def on_end(self, ctx: StrategyContext) -> None:
        """Called once after the last bar.  Override for cleanup/logging."""
        pass
