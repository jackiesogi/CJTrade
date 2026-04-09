"""
pkgs/strategy/support_resistance.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Support & Resistance Level strategy.

Behavior
--------
- Calculate the highest high (resistance) and lowest low (support) over the last N days.
- BUY near support levels (with breakout confirmation).
- SELL near resistance levels.
- Optional: BUY on breakout above resistance (trend following).

Usage
-----
from cjtrade.pkgs.strategy.support_resistance import SupportResistanceStrategy
strategy = SupportResistanceStrategy(lookback_days=20, breakout_mode=True)

run_oneshot(symbol="2330", start="2023-01-01", strategy=strategy)
"""
from __future__ import annotations

import logging
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List

import numpy as np
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)


class SupportResistanceStrategy(BaseStrategy):
    """Support & Resistance levels strategy.

    Tracks highest high and lowest low over a lookback period.
    - BUY when price approaches support (from above)
    - SELL when price approaches resistance (from below)
    - Optional: BUY on resistance breakout (if breakout_mode=True)

    Parameters (constructor or via ctx.params)
    - lookback_days: Number of days to look back for S/R levels (default: 20)
    - support_threshold_pct: How close to support before buying (e.g. 0.01 = 1%)
    - resistance_threshold_pct: How close to resistance before selling
    - breakout_mode: If True, also buy when price breaks above resistance
    - max_position_pct: Max position size as fraction of equity
    """

    name = "SupportResistance"

    def __init__(
        self,
        lookback_days: int = 20,
        support_threshold_pct: float = 0.01,
        resistance_threshold_pct: float = 0.01,
        breakout_mode: bool = False,
        max_position_pct: float = 0.05,
    ) -> None:
        self._lookback_days = lookback_days
        self._support_threshold_pct = support_threshold_pct
        self._resistance_threshold_pct = resistance_threshold_pct
        self._breakout_mode = breakout_mode
        self._max_position_pct = max_position_pct
        # Track previous close and breakout state per symbol
        self._prev_close: Dict[str, float] = {}
        self._resistance_broken: Dict[str, bool] = {}
        # Will be set in on_start based on kbar interval detected from price history
        self._bars_per_day: int = 270  # default for 1m bars, will auto-detect

    def on_start(self, ctx: StrategyContext) -> None:
        p = ctx.params
        self._lookback_days = int(p.get("sr_lookback_days", self._lookback_days))
        self._support_threshold_pct = float(p.get("sr_support_threshold_pct", self._support_threshold_pct))
        self._resistance_threshold_pct = float(p.get("sr_resistance_threshold_pct", self._resistance_threshold_pct))
        self._breakout_mode = p.get("sr_breakout_mode", self._breakout_mode)
        self._max_position_pct = float(p.get("risk_max_position_pct", self._max_position_pct))

        # Auto-detect bars per day based on kbar interval
        # This allows strategy to work with both 1m and 1d (or any interval)
        interval_hint = p.get("sr_interval", "1m")  # can be overridden
        if interval_hint.lower() == "1d":
            self._bars_per_day = 1  # 1d kbar = 1 bar per day
        elif interval_hint.lower() == "1h":
            self._bars_per_day = 7  # rough estimate for trading hours
        else:  # default 1m
            self._bars_per_day = 270  # ~270 minutes per trading day

        log.info(
            f"[{self.name}] lookback={self._lookback_days}d "
            f"support_thr={self._support_threshold_pct*100:.2f}% "
            f"resistance_thr={self._resistance_threshold_pct*100:.2f}% "
            f"breakout_mode={self._breakout_mode} "
            f"(bars_per_day={self._bars_per_day})"
        )

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Emit signals based on support/resistance levels."""
        prices = ctx.prices(bar.symbol)

        # Need enough history (based on detected/configured bars_per_day)
        min_bars_needed = self._lookback_days * self._bars_per_day
        if len(prices) < min_bars_needed:
            return []

        # Get the recent price window
        recent_prices = prices[-min_bars_needed:]

        # Calculate support (lowest low) and resistance (highest high)
        support = float(np.min(recent_prices))
        resistance = float(np.max(recent_prices))

        price = bar.close
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Calculate thresholds
        support_buy_level = support * (1 + self._support_threshold_pct)
        resistance_sell_level = resistance * (1 - self._resistance_threshold_pct)

        signals: List[Signal] = []

        # --- BUY LOGIC ---
        # 1. Buy near support (price touches or goes slightly above support)
        if (price <= support_buy_level and
            not ctx.has_position(bar.symbol)):
            qty = ctx.calc_qty(price, self._max_position_pct)
            if qty > 0:
                log.info(
                    f"ts: {ts_str} | BUY {bar.symbol} @ {price:.2f} "
                    f"(near support={support:.2f})"
                )
                signals.append(Signal(
                    action="BUY",
                    symbol=bar.symbol,
                    quantity=qty,
                    price=price,
                    reason=f"Support level buy (S={support:.2f} R={resistance:.2f})",
                    meta={"support": support, "resistance": resistance, "price": price},
                ))

        # 2. Buy on breakout above resistance (if enabled and price breaks up)
        elif (self._breakout_mode and
              price > resistance and
              not self._resistance_broken.get(bar.symbol, False) and
              not ctx.has_position(bar.symbol)):
            qty = ctx.calc_qty(price, self._max_position_pct)
            if qty > 0:
                self._resistance_broken[bar.symbol] = True
                log.info(
                    f"ts: {ts_str} | BUY {bar.symbol} @ {price:.2f} "
                    f"(resistance breakout, R={resistance:.2f})"
                )
                signals.append(Signal(
                    action="BUY",
                    symbol=bar.symbol,
                    quantity=qty,
                    price=price,
                    reason=f"Resistance breakout buy (R={resistance:.2f})",
                    meta={"support": support, "resistance": resistance, "price": price},
                ))

        # --- SELL LOGIC ---
        # Sell near resistance (price approaches or touches resistance)
        if (price >= resistance_sell_level and
            ctx.has_position(bar.symbol)):
            qty = ctx.position_qty(bar.symbol)
            log.info(
                f"ts: {ts_str} | SELL {bar.symbol} @ {price:.2f} "
                f"(near resistance={resistance:.2f})"
            )
            signals.append(Signal(
                action="SELL",
                symbol=bar.symbol,
                quantity=qty,
                price=price,
                reason=f"Resistance level sell (S={support:.2f} R={resistance:.2f})",
                meta={"support": support, "resistance": resistance, "price": price},
            ))
            # Reset breakout flag after selling
            self._resistance_broken[bar.symbol] = False

        # Store previous close for trend detection (if needed in future)
        self._prev_close[bar.symbol] = price

        return signals

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Log fills for debugging."""
        if fill.action.upper() == "BUY":
            log.debug(
                f"[{self.name}] BUY filled for {fill.symbol} @ {fill.price:.2f} "
                f"qty={fill.quantity}"
            )
        elif fill.action.upper() == "SELL":
            log.debug(
                f"[{self.name}] SELL filled for {fill.symbol} @ {fill.price:.2f} "
                f"qty={fill.quantity}"
            )

    def on_end(self, ctx: StrategyContext) -> None:
        """Called at end of backtest."""
        log.info(
            f"[{self.name}] Done – equity {ctx.equity:,.0f}  "
            f"balance {ctx.balance:,.0f}  "
            f"positions: {[p['symbol'] for p in ctx.positions]}"
        )
