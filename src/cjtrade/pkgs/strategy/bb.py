"""
pkgs/strategy/bb_1m.py
~~~~~~~~~~~~~~~~~~~~~~~
Bollinger Band mean-reversion strategy using TA-Lib (matches arenax.py).

Copy this file, rename the class, and implement your own logic in on_bar().

Run it:
    from cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest import run_oneshot
    from cjtrade.pkgs.strategy.bb_1m import BollingerStrategy

    run_oneshot(symbol="2330", start="2023-01-01", strategy=BollingerStrategy())
"""
from __future__ import annotations

import logging
from typing import List

import numpy as np
from cjtrade.pkgs.analytics.technical import *
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)

class BollingerStrategy(BaseStrategy):
    """Bollinger Band mean-reversion strategy using TA-Lib.

    Matches the behavior of arenax.py's calculate_bollinger_bands_mock().
    Buys when price touches lower band, sells when it touches upper band.
    Keeps at most one position (no pyramiding).
    """
    name = "BB"
    long_name = "BollingerBands"

    # Monitor state. Declared at class level as well as set in on_start so
    # monitors() is safe to call before the first bar, which a runner polling
    # on a timer will do.
    _window = 0
    _min_bw = 0.0
    _max_pct = 0.0
    _n_bars = 0
    _n_upper = 0
    _n_lower = 0
    _n_cross = 0
    _n_signals = 0
    _upper = 0.0
    _middle = 0.0
    _lower = 0.0
    _bw = 0.0
    _bw_sum = 0.0
    _bw_n = 0
    _prev_above_mid = None
    _last_reason = "not started"

    def on_start(self, ctx):
        p = ctx.params
        # Read from params (support both old and new param names for backward compatibility)
        self._window = int(p.get("bb__window_size", p.get("bb_window_size", 20)))
        self._min_bw = float(p.get("bb__min_width_pct", p.get("bb_min_width_pct", 0.01)))
        self._max_pct = float(p.get("risk__max_position_pct", p.get("risk_max_position_pct", 0.05)))
        self._n_bars = self._n_upper = self._n_lower = 0
        self._n_cross = self._n_signals = 0
        self._upper = self._middle = self._lower = self._bw = 0.0
        self._bw_sum, self._bw_n = 0.0, 0
        self._prev_above_mid = None
        self._last_reason = "no bars yet"
        log.info(f"[{self.name}] window={self._window} min_bw={self._min_bw*100:.2f}%")

    # ── monitoring ────────────────────────────────────────────────────────────

    def _observe(self, price: float, upper: float, middle: float,
                 lower: float, bw: float) -> None:
        """Update the monitor counters. Makes no decisions.

        Touches are counted whenever the bands exist, including inside a
        squeeze this strategy will not trade: a touch is a fact about the
        market, and `regime` already reports whether it was actionable.
        Counting only tradeable touches would make the number depend on a
        config value and stop it being comparable across runs.
        """
        if price >= upper:
            self._n_upper += 1
        if price <= lower:
            self._n_lower += 1

        above = price > middle
        if self._prev_above_mid is not None and above != self._prev_above_mid:
            self._n_cross += 1
        self._prev_above_mid = above

        self._upper, self._middle, self._lower, self._bw = upper, middle, lower, bw
        self._bw_sum += bw
        self._bw_n += 1

    def monitors(self) -> dict:
        """See BaseStrategy.monitors. Plain floats, ints and strings only."""
        bw_avg = self._bw_sum / self._bw_n if self._bw_n else 0.0
        # Volatility is relative to this symbol's own history rather than an
        # absolute threshold: a 0.5% band is wide for an ETF and narrow for a
        # small cap, so a fixed cutoff would mean different things per symbol.
        if self._bw_n == 0:
            volatility = "unknown"
        elif self._bw > bw_avg * 1.2:
            volatility = "high"
        elif self._bw < bw_avg * 0.8:
            volatility = "low"
        else:
            volatility = "normal"

        return {
            "bars_seen":         self._n_bars,
            "window":            self._window,
            "upper":             round(self._upper, 2),
            "middle":            round(self._middle, 2),
            "lower":             round(self._lower, 2),
            "bandwidth_pct":     round(self._bw * 100, 3),
            "bandwidth_avg_pct": round(bw_avg * 100, 3),
            "volatility":        volatility,
            # Whether the squeeze gate would let a touch through right now.
            "regime":            "tradeable" if self._bw >= self._min_bw else "squeeze",
            "upper_touches":     self._n_upper,
            "lower_touches":     self._n_lower,
            "mid_crossings":     self._n_cross,
            "signals_emitted":   self._n_signals,
            "last_decision":     self._last_reason,
        }

    def on_bar(self, bar, ctx):
        self._n_bars += 1
        prices = ctx.prices(bar.symbol)
        # Need enough data for TA-Lib BB calculation
        if len(prices) < self._window:
            self._last_reason = (f"warming up: {len(prices)} of "
                                 f"{self._window} bars")
            return []

        # Only slice the last _window prices — TA-Lib only needs exactly this
        # many points to compute the latest BB values. Avoids O(n) numpy
        # allocation that grows with the entire price history.
        prices_array = np.array(prices[-self._window:], dtype=float)
        upper_bands, middle_bands, lower_bands = ta.bb(
            prices_array,
            timeperiod=self._window,
            nbdevup=2,
            nbdevdn=2
        )

        # Get the latest BB values
        upper = float(upper_bands[-1])
        middle = float(middle_bands[-1])
        lower = float(lower_bands[-1])
        bw = (upper - lower) / middle if middle > 0 else 0.0
        price = bar.close

        self._observe(price, upper, middle, lower, bw)

        # Skip if band is too narrow
        if bw < self._min_bw:
            self._last_reason = (f"squeeze: bandwidth {bw*100:.3f}% under the "
                                 f"{self._min_bw*100:.3f}% floor")
            return []

        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        holding = ctx.has_position(bar.symbol)

        # BUY: price touches or breaks below lower band and we don't have a position
        if price <= lower and not holding:
            qty = ctx.calc_qty(price, self._max_pct)
            if qty > 0:
                self._n_signals += 1
                self._last_reason = (f"BUY {qty} @ {price:.2f} on lower-band "
                                     f"touch (lower={lower:.2f})")
                log.info(f"ts: {ts_str} | BUY {bar.symbol} @ {price:.2f} * {qty} shares (BB lower={lower:.2f})")
                return [type("Signal", (), {
                    "action": "BUY", "symbol": bar.symbol,
                    "quantity": qty, "price": price,
                    "reason": f"BB lower touch (bw={bw*100:.2f}%)",
                    "meta": {"upper": upper, "middle": middle, "lower": lower},
                })]
            self._last_reason = (f"lower-band touch at {price:.2f} but size is "
                                 f"0: {self._max_pct:.0%} of equity "
                                 f"{ctx.equity:,.0f} buys nothing at this price")
            return []

        # SELL: price touches or rises above upper band and we hold a position
        elif price >= upper and holding:
            qty = ctx.position_qty(bar.symbol)
            self._n_signals += 1
            self._last_reason = (f"SELL {qty} @ {price:.2f} on upper-band "
                                 f"touch (upper={upper:.2f})")
            log.info(f"ts: {ts_str} | SELL {bar.symbol} @ {price:.2f} * {qty} shares (BB upper={upper:.2f})")
            return [type("Signal", (), {
                "action": "SELL", "symbol": bar.symbol,
                "quantity": qty, "price": price,
                "reason": f"BB upper touch (bw={bw*100:.2f}%)",
                "meta": {"upper": upper, "middle": middle, "lower": lower},
            })]

        # No actionable signal this bar. Which of the three it was matters:
        # "between the bands" is the market doing nothing, while the other two
        # are the strategy declining a touch it saw, and only one of those is
        # ever the thing you are looking for when a run trades less than
        # expected.
        if price <= lower:
            self._last_reason = (f"lower-band touch at {price:.2f} ignored: "
                                 f"already holding {ctx.position_qty(bar.symbol)}")
        elif price >= upper:
            self._last_reason = (f"upper-band touch at {price:.2f} ignored: "
                                 f"no position to sell")
        else:
            self._last_reason = (f"price {price:.2f} inside the bands "
                                 f"[{lower:.2f}, {upper:.2f}]")
        return []
