"""
pkgs/strategy/donchian.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Pure Donchian Breakout Strategy.

Behavior
--------
- Calculate highest high and lowest low over the last N days
- BUY when price breaks above the highest high (uptrend confirmation)
- SELL when price breaks below the lowest low (downtrend confirmation)
- Trend-following approach (works best in trending markets)

Parameters (via ctx.params or constructor defaults)
- donchian__period: Lookback period in days (default: 20)
- donchian__breakout_mode: 'close' (price closes above/below) or 'touch' (touches) (default: 'close')
- donchian__trailing_stop_pct: Optional trailing stop as % of entry price (default: 0.0 = disabled)
- risk__max_position_pct: Max position size (default: 0.05)

Usage
-----
from cjtrade.pkgs.strategy.donchian import DonchianBreakoutStrategy
strategy = DonchianBreakoutStrategy(period=20, breakout_mode='close')

run_oneshot(symbol="2330", start="2023-01-01", strategy=strategy)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict
from typing import List

from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)


class DonchianBreakoutStrategy(BaseStrategy):
    """Pure Donchian Channel breakout trending strategy.

    Tracks the highest high and lowest low over a lookback period.
    - BUY when price breaks above the highest high (new N-day high)
    - SELL when price breaks below the lowest low (new N-day low)

    This is a classic trend-following approach that works best in
    strongly trending markets.

    Parameters (constructor or via ctx.params)
    - period: Number of days to look back for Donchian highs/lows (default: 20)
    - breakout_mode: 'close' = close above/below, 'touch' = touches (default: 'close')
    - trailing_stop_pct: Trailing stop as % of entry (0.0 = disabled) (default: 0.0)
    - max_position_pct: Max position size as fraction of equity (default: 0.05)
    """

    name = "Donchian"
    long_name = "Donchian Breakout"

    def __init__(
        self,
        period: int = 20,
        breakout_mode: str = "close",
        trailing_stop_pct: float = 0.0,
        max_position_pct: float = 0.05,
    ) -> None:
        self._period = period
        self._breakout_mode = breakout_mode  # 'close' or 'touch'
        self._trailing_stop_pct = trailing_stop_pct
        self._max_position_pct = max_position_pct

        # Per-symbol state
        self._prev_close: Dict[str, float] = {}
        self._entry_price: Dict[str, float] = {}  # For trailing stop

        # Bars per day calculation (auto-detect from interval)
        self._bars_per_day: int = 270  # default for 1m

    def on_start(self, ctx: StrategyContext) -> None:
        """Initialize parameters from ctx.params."""
        p = ctx.params

        # Read Donchian parameters (support both old and new naming)
        self._period = int(p.get("donchian__period", p.get("donchian_period", self._period)))
        self._breakout_mode = p.get("donchian__breakout_mode", p.get("donchian_breakout_mode", self._breakout_mode))
        self._trailing_stop_pct = float(p.get("donchian__trailing_stop_pct", p.get("donchian_trailing_stop_pct", self._trailing_stop_pct)))
        self._max_position_pct = float(p.get("risk__max_position_pct", p.get("risk_max_position_pct", self._max_position_pct)))

        # Auto-detect bars per day from interval hint
        interval_hint = p.get("sr__interval", p.get("sr_interval", "1m"))
        if interval_hint.lower() == "1d":
            self._bars_per_day = 1
        elif interval_hint.lower() == "1h":
            self._bars_per_day = 7
        elif interval_hint.lower() == "5m":
            self._bars_per_day = 54
        else:  # default 1m
            self._bars_per_day = 270

        log.info(
            f"[{self.name}] period={self._period}d "
            f"breakout_mode={self._breakout_mode} "
            f"trailing_stop={self._trailing_stop_pct*100:.2f}% "
            f"max_pos={self._max_position_pct*100:.2f}%"
        )

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Process incoming bar and generate signals."""
        symbol = bar.symbol
        close = bar.close
        high = bar.high
        low = bar.low
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Ensure we have history
        prices = ctx.prices(symbol)
        bars_lookback = self._period * self._bars_per_day

        if len(prices) < bars_lookback:
            # Not enough data yet
            self._prev_close[symbol] = close
            return []

        # Get Donchian channel
        recent_closes = prices[-bars_lookback:]
        donchian_high = max(recent_closes)
        donchian_low = min(recent_closes)

        prev_close = self._prev_close.get(symbol, close)
        signals: List[Signal] = []

        # --- BUY LOGIC ---
        # Breakout above Donchian high
        is_above_breakout = False
        if self._breakout_mode == "close":
            # Close above highest high
            is_above_breakout = prev_close <= donchian_high and close > donchian_high
        else:  # touch mode
            # Price touches or goes above
            is_above_breakout = high > donchian_high and not ctx.has_position(symbol)

        if is_above_breakout and not ctx.has_position(symbol):
            qty = ctx.calc_qty(close, self._max_position_pct)
            if qty > 0:
                self._entry_price[symbol] = close
                log.info(
                    f"ts: {ts_str} | BUY {symbol} @ {close:.2f} "
                    f"* {qty} shares (Donchian breakout above {donchian_high:.2f})"
                )
                signals.append(Signal(
                    action="BUY",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"Donchian breakout above channel high {donchian_high:.2f}",
                    meta={
                        "donchian_high": donchian_high,
                        "donchian_low": donchian_low,
                        "breakout": "up",
                    }
                ))

        # --- SELL LOGIC ---
        # Check trailing stop first (if position exists and has entry price)
        if ctx.has_position(symbol) and symbol in self._entry_price:
            entry_price = self._entry_price[symbol]
            trailing_stop_level = entry_price * (1 - self._trailing_stop_pct)

            if self._trailing_stop_pct > 0 and close < trailing_stop_level:
                qty = ctx.position_qty(symbol)
                log.info(
                    f"ts: {ts_str} | SELL {symbol} @ {close:.2f} "
                    f"* {qty} shares (trailing stop, entry was {entry_price:.2f})"
                )
                signals.append(Signal(
                    action="SELL",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"Trailing stop triggered ({self._trailing_stop_pct*100:.2f}%)",
                    meta={"stop_type": "trailing"}
                ))
                del self._entry_price[symbol]
                self._prev_close[symbol] = close
                return signals

        # Breakout below Donchian low (hard stop)
        is_below_breakout = False
        if self._breakout_mode == "close":
            # Close below lowest low
            is_below_breakout = prev_close >= donchian_low and close < donchian_low
        else:  # touch mode
            # Price touches or goes below
            is_below_breakout = low < donchian_low

        if is_below_breakout and ctx.has_position(symbol):
            qty = ctx.position_qty(symbol)
            log.info(
                f"ts: {ts_str} | SELL {symbol} @ {close:.2f} "
                f"* {qty} shares (Donchian breakout below {donchian_low:.2f})"
            )
            signals.append(Signal(
                action="SELL",
                symbol=symbol,
                quantity=qty,
                price=close,
                reason=f"Donchian breakout below channel low {donchian_low:.2f}",
                meta={
                    "donchian_high": donchian_high,
                    "donchian_low": donchian_low,
                    "breakout": "down",
                }
            ))
            if symbol in self._entry_price:
                del self._entry_price[symbol]

        # Store state
        self._prev_close[symbol] = close
        return signals

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Called after a fill is executed."""
        log.info(f"[{self.name}] {fill.action} {fill.quantity} @ {fill.price} ({fill.symbol})")

    def on_end(self, ctx: StrategyContext) -> None:
        """Called at end of backtest."""
        log.info(f"[{self.name}] Backtest completed")
