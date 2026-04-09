"""
pkgs/strategy/dca_monthly.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dollar-Cost Averaging monthly strategy.

Behavior
--------
- On each bar, check when the strategy last bought this symbol.
- If no prior buy or at least 30 days have passed since the last buy,
  emit a BUY signal sized by ctx.calc_qty(price, max_pct).
- No SELL logic (user requested no sell case for now).

Usage
-----
from cjtrade.pkgs.strategy.dca_monthly import DCA_Monthly
strategy = DCA_Monthly(max_position_pct=0.03)
"""
from __future__ import annotations

import logging
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List

from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)

DCA_MONTHLY_AMOUNT = 10000

class DCA_Monthly(BaseStrategy):
    """Buy once every 30 days (per-symbol).

    Parameters (constructor or via ctx.params)
    - max_position_pct: fraction of equity to allocate on each buy (passed to ctx.calc_qty)
    """

    name = "DCA_Monthly"

    def __init__(self, max_position_pct: float = 0.03) -> None:
        self._max_position_pct = max_position_pct
        # track last buy time per symbol
        self._last_buy_time: Dict[str, "datetime"] = {}

    def on_start(self, ctx: StrategyContext) -> None:
        p = ctx.params
        self._max_position_pct = float(p.get("dca_max_position_pct", self._max_position_pct))
        # allow externally provided last_buy_time (ISO string) if desired
        maybe = p.get("dca_last_buy_time")
        if isinstance(maybe, dict):
            # map of symbol -> ISO timestamp
            for sym, iso in maybe.items():
                try:
                    self._last_buy_time[sym] = datetime.fromisoformat(iso)
                except Exception:
                    log.debug("dca_monthly: ignoring invalid last_buy_time for %s", sym)

        log.info(f"[{self.name}] max_position_pct={self._max_position_pct:.3f}")

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Emit a BUY signal if >=30 days since last buy for this symbol.

        We don't block buys if a position already exists; this implements
        a pure DCA accumulate behaviour.
        """
        now = ctx.timestamp
        sym = bar.symbol
        price = bar.close

        last = self._last_buy_time.get(sym)
        if last is not None and (now - last) < timedelta(days=30):
            return []

        # decide quantity using the context helper (returns lots)
        # qty = ctx.calc_qty(price, max_pct=self._max_position_pct)
        qty = int(DCA_MONTHLY_AMOUNT / price)
        if qty <= 0:
            return []

        # Update last buy time NOW (when signal is issued, not when filled)
        # This prevents repeated signals if the order is rejected
        self._last_buy_time[sym] = now

        # emit BUY signal
        reason = f"DCA monthly (since={last.isoformat() if last else 'never'})"
        sig = Signal(action="BUY", symbol=sym, quantity=qty, price=price, reason=reason)
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"ts: {ts_str} | BUY {bar.symbol} @ {price:.2f} * {qty} shares")
        return [sig]

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Log fills for debugging (last_buy_time is now updated in on_bar)."""
        if fill.action.upper() == "BUY":
            log.debug(f"[{self.name}] BUY filled for {fill.symbol} @ {fill.price:.2f}")
