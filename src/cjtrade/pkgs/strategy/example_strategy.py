"""
pkgs/strategy/example_strategy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Example strategy: Bollinger Band mean-reversion (standalone, copy-paste ready).

Copy this file, rename the class, and implement your own logic in on_bar().

Run it:
    from cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest import run_oneshot
    from cjtrade.pkgs.strategy.example_strategy import BollingerStrategy

    run_oneshot(symbol="2330", start="2023-01-01", strategy=BollingerStrategy())
"""
from __future__ import annotations

import logging
from typing import List

import numpy as np
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)


class BollingerStrategy(BaseStrategy):
    """Bollinger Band (20-period, 2σ) mean-reversion.

    Entry  : buy when close ≤ lower band (no existing position)
    Exit   : sell all when close ≥ upper band
    Filter : skip when band width < min_width_pct (consolidation)
    """

    name = "BollingerStrategy"

    # Default parameters – override via ctx.params or constructor kwargs
    def __init__(
        self,
        window: int   = 20,
        num_std: float = 2.0,
        min_width_pct: float = 0.01,
        max_position_pct: float = 0.05,
    ) -> None:
        self._window          = window
        self._num_std         = num_std
        self._min_width_pct   = min_width_pct
        self._max_position_pct = max_position_pct

    # ------------------------------------------------------------------
    def on_start(self, ctx: StrategyContext) -> None:
        # Params passed via BacktestEngine(..., params={...}) take precedence
        p = ctx.params
        self._window          = int(p.get("bb_window_size",       self._window))
        self._num_std         = float(p.get("bb_num_std",         self._num_std))
        self._min_width_pct   = float(p.get("bb_min_width_pct",   self._min_width_pct))
        self._max_position_pct = float(p.get("risk_max_position_pct", self._max_position_pct))
        log.info(
            f"[{self.name}] window={self._window}  std={self._num_std}  "
            f"min_bw={self._min_width_pct*100:.2f}%  max_pos={self._max_position_pct*100:.1f}%"
        )

    # ------------------------------------------------------------------
    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        prices = ctx.prices(bar.symbol)
        if len(prices) < self._window:
            return []

        arr    = np.array(prices[-self._window:], dtype=float)
        middle = arr.mean()
        std    = arr.std(ddof=1)
        upper  = middle + self._num_std * std
        lower  = middle - self._num_std * std
        bw     = (upper - lower) / middle if middle > 0 else 0.0

        price  = bar.close

        if bw < self._min_width_pct:
            return []  # band too narrow → no trade

        signals: List[Signal] = []

        if price <= lower and not ctx.has_position(bar.symbol):
            qty = ctx.calc_qty(price, self._max_position_pct)
            if qty > 0:
                signals.append(Signal(
                    action="BUY",
                    symbol=bar.symbol,
                    quantity=qty,
                    price=price,
                    reason=f"BB lower (bw={bw*100:.2f}%)",
                    meta={"upper": upper, "middle": middle, "lower": lower},
                ))

        elif price >= upper and ctx.has_position(bar.symbol):
            qty = ctx.position_qty(bar.symbol)
            signals.append(Signal(
                action="SELL",
                symbol=bar.symbol,
                quantity=qty,
                price=price,
                reason=f"BB upper (bw={bw*100:.2f}%)",
                meta={"upper": upper, "middle": middle, "lower": lower},
            ))

        return signals

    # ------------------------------------------------------------------
    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        log.info(
            f"[{self.name}] FILL {fill.action} {fill.quantity}張 {fill.symbol} "
            f"@ {fill.price:.2f}  reason={fill.reason}"
        )

    # ------------------------------------------------------------------
    def on_end(self, ctx: StrategyContext) -> None:
        log.info(
            f"[{self.name}] Done – equity {ctx.equity:,.0f}  "
            f"balance {ctx.balance:,.0f}  "
            f"positions: {[p['symbol'] for p in ctx.positions]}"
        )
