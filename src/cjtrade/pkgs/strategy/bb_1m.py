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
    name = "BollingerBands"

    def on_start(self, ctx):
        p = ctx.params
        # Read from config (same as arenax.py)
        self._window   = int(p.get("bb_window_size",      100))
        # self._min_bw   = float(p.get("bb_min_width_pct",  0.01))
        self._min_bw   = float(p.get("bb_min_width_pct",  0.02))
        self._max_pct  = float(p.get("risk_max_position_pct", 0.05))
        log.info(f"[{self.name}] window={self._window} min_bw={self._min_bw*100:.2f}%")

    def on_bar(self, bar, ctx):
        prices = ctx.prices(bar.symbol)
        # Need enough data for TA-Lib BB calculation
        if len(prices) < self._window:
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

        # Skip if band is too narrow
        if bw < self._min_bw:
            return []

        price = bar.close
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # BUY: price touches or breaks below lower band and we don't have a position
        if price <= lower and not ctx.has_position(bar.symbol):
            qty = ctx.calc_qty(price, self._max_pct)
            if qty > 0:
                log.info(f"ts: {ts_str} | BUY {bar.symbol} @ {price:.2f} * {qty} shares (BB lower={lower:.2f})")
                return [type("Signal", (), {
                    "action": "BUY", "symbol": bar.symbol,
                    "quantity": qty, "price": price,
                    "reason": f"BB lower touch (bw={bw*100:.2f}%)",
                    "meta": {"upper": upper, "middle": middle, "lower": lower},
                })]

        # SELL: price touches or rises above upper band and we hold a position
        elif price >= upper and ctx.has_position(bar.symbol):
            qty = ctx.position_qty(bar.symbol)
            log.info(f"ts: {ts_str} | SELL {bar.symbol} @ {price:.2f} * {qty} shares (BB upper={upper:.2f})")
            return [type("Signal", (), {
                "action": "SELL", "symbol": bar.symbol,
                "quantity": qty, "price": price,
                "reason": f"BB upper touch (bw={bw*100:.2f}%)",
                "meta": {"upper": upper, "middle": middle, "lower": lower},
            })]

        # No actionable signal this bar
        return []
