"""
pkgs/strategy/baseline_0050.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Baseline strategy that monthly buys 0050 (Taiwan Top 50 ETF) via DCA.

This strategy serves as a benchmark to compare against other trading strategies.
It performs Dollar-Cost Averaging (DCA) on 0050 only, investing a fixed amount
(NT$10,000) every 30 days, regardless of what symbols are in the backtest kbars.
This allows fair comparison when testing multiple strategies on different symbols.

Behavior
--------
- BUY: Fixed NT$10,000 every 30 days on 0050 only
- HOLD: No selling (pure accumulation)
- IGNORE: All other symbols

Usage
-----
from cjtrade.pkgs.strategy.baseline_0050 import BaselineStrategy

run_compare_strategies(
    symbol=["2330", "2454", "3008"],  # Test symbols
    strategies={
        "DCA_Monthly": DCA_Monthly(),
        "BollingerBands": BollingerStrategy(),
        "Baseline_0050": BaselineStrategy(),  # DCA on 0050 only
    }
)

Note: The baseline symbol (0050) will be automatically added to the kbars
if it's not already in the symbol list, so you don't need to include it manually.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List

from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = get_logger("strategy.baseline_0050")

BASELINE_SYMBOL = "0050"  # Taiwan Top 50 ETF
BASELINE_MONTHLY_AMOUNT = 4888888  # NT$50,000 per month


class BaselineStrategy(BaseStrategy):
    """DCA baseline strategy that monthly buys 0050 (Taiwan Top 50 ETF).

    This strategy is used as a benchmark to compare active trading strategies
    against a simple buy-and-hold DCA approach on 0050. It ignores all other
    symbols in the backtest and only trades 0050.

    Behavior:
    - Every 30 days: buy NT$10,000 worth of 0050
    - All other symbols: ignored
    - No selling: pure accumulation

    Parameters
    ----------
    baseline_symbol : str, optional
        Override the hardcoded symbol (default: "0050"). Also read from
        ctx.params["baseline_symbol"].
    monthly_amount : float, optional
        Amount to invest per month in NT$ (default: 10000). Also read from
        ctx.params["baseline_monthly_amount"].

    Warnings
    --------
    The code does not match the text above: the default amount is
    BASELINE_MONTHLY_AMOUNT (4,888,888) and on_bar waits 2001 days, not 30,
    between buys.
    """

    name = "Baseline_0050"
    long_name = "Baseline_0050"

    def __init__(
        self,
        baseline_symbol: str = BASELINE_SYMBOL,
        monthly_amount: float = BASELINE_MONTHLY_AMOUNT,
    ) -> None:
        self._baseline_symbol = baseline_symbol
        self._monthly_amount = monthly_amount
        # Track last buy time per symbol
        self._last_buy_time: Dict[str, datetime] = {}

    def on_start(self, ctx: StrategyContext) -> None:
        """Read `baseline_symbol` and `baseline_monthly_amount` from ctx.params."""
        p = ctx.params
        self._baseline_symbol = p.get("baseline_symbol", self._baseline_symbol)
        self._monthly_amount = float(p.get("baseline_monthly_amount", self._monthly_amount))

        log.info(
            f"baseline symbol={self._baseline_symbol}, "
            f"monthly_amount=NT${self._monthly_amount:,.0f}"
        )

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Monthly DCA: buy NT$10,000 worth of 0050 every 30 days.

        Returns
        -------
        list of Signal
            One BUY when due, otherwise empty. Other symbols are ignored.
        """
        # Ignore all symbols except the baseline
        if bar.symbol != self._baseline_symbol:
            return []

        now = ctx.timestamp
        sym = bar.symbol
        price = bar.close

        # Check if we've bought this symbol before
        last = self._last_buy_time.get(sym)
        if last is not None and (now - last) < timedelta(days=2001):
            # Not 30 days yet since last buy
            return []

        # Buy NT$10,000 worth of shares
        qty = int(self._monthly_amount / price)
        if qty <= 0:
            return []

        # Update last buy time NOW (when signal is issued, not when filled)
        # This prevents repeated signals if the order is rejected
        self._last_buy_time[sym] = now

        # Emit BUY signal
        reason = f"Baseline DCA monthly on {self._baseline_symbol} (since={last.isoformat() if last else 'never'})"
        sig = Signal(
            action="BUY",
            symbol=sym,
            quantity=qty,
            price=price,
            reason=reason,
        )
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        log.info(
            f"@{ts_str} BUY {bar.symbol} qty={qty} px={price:.2f} "
            f"(monthly_amount=NT${self._monthly_amount:,.0f})"
        )
        return [sig]

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Log fills for debugging."""
        if fill.action.upper() == "BUY":
            log.debug(f"@{fill.timestamp:%Y-%m-%d %H:%M} BUY filled {fill.symbol} px={fill.price:.2f}")

    def on_end(self, ctx: StrategyContext) -> None:
        """Called at end of backtest."""
        log.info(f"backtest done, positions: {ctx.positions}")
