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
        monitors() → dict              ← optional; what to watch, and why the
                                         bar did or did not produce a signal
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
    tax: float = 0.0
    slippage_cost: float = 0.0
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

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def plots(self) -> Dict[str, float]:
        """Series this strategy wants drawn against the price, this bar.

        Separate from monitors() because the two are consumed differently: a
        monitor is a number to read now, a plot is a point in a series
        accumulated over the run. A runner samples this once per bar and keeps
        the history; the strategy only reports the current value.

        Numbers only, and in the same units as the price where that makes
        sense -- bands, moving averages, breakout levels. A value on a
        different scale (an oscillator, a count) is still fine; it is the
        chart's job to put it on its own axis.

        Default is empty, so a strategy that does not care has nothing to say
        and nothing breaks. The price itself is never returned here: every
        runner already knows the bar it just handed over, and a strategy
        re-reporting it would be a second answer that could disagree.
        """
        return {}

    def monitors(self) -> Dict[str, Any]:
        """Named values this strategy wants watched. Read-only and cheap.

        Called by a runner after on_bar, as often as once per bar. Return
        whatever makes this strategy's behaviour legible: indicator levels,
        counters, a regime label, and above all WHY the last bar did or did not
        produce a signal -- on_bar returns an empty list for several different
        reasons and the caller cannot tell them apart.

        Returns
        -------
        dict[str, Any]
            Scalars and strings only. A runner may put this on a wire or in a
            table, so nothing here should be a numpy type, a model object, or
            anything that needs the strategy alive to interpret.

        Default is empty, so an existing strategy keeps working and simply has
        nothing to show. Deliberately not abstract for the same reason.

        Accumulated values (counters, running means) live on the strategy and
        are updated in on_bar; this method only reads them. A caller that wants
        rates or deltas keeps its own history of these snapshots -- that is why
        there is no need to declare which values are counters and which are
        gauges.
        """
        return {}
