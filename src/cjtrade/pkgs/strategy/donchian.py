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
- donchian__period: Lookback in BARS, excluding the current one (default: 20)
- donchian__breakout_mode: 'close' (price closes above/below) or 'touch' (touches) (default: 'close')
- donchian__trailing_stop_pct: Trailing stop as % below the peak since entry (default: 0.0 = disabled)
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
    - period: Bars to look back for the channel, current bar excluded (default: 20)
    - breakout_mode: 'close' = close above/below, 'touch' = touches (default: 'close')
    - trailing_stop_pct: Stop as % below the peak since entry (0.0 = disabled)
    - max_position_pct: Max position size as fraction of equity (default: 0.05)

    Note on 'touch' mode: it reads bar.high/bar.low, which only describe this
    bar on a kbar feed. Under the trading engine the bars come from snapshots,
    where high and low are the whole trading DAY so far (see
    Kbar.from_snapshot), so 'touch' means something different there. 'close'
    mode reads only closes and behaves the same on both feeds.
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
        self._entry_price: Dict[str, float] = {}
        # Highest close seen since entry, per symbol. A trailing stop has to
        # trail something, and measuring the drawdown from the entry price
        # instead -- which is what this did -- is a fixed stop wearing the
        # wrong name: it can never move up, so a position that doubled was
        # still stopped out at entry minus the same percentage.
        self._peak: Dict[str, float] = {}

    def on_start(self, ctx: StrategyContext) -> None:
        """Initialize parameters from ctx.params."""
        p = ctx.params

        # Read Donchian parameters (support both old and new naming)
        self._period = int(p.get("donchian__period", p.get("donchian_period", self._period)))
        self._breakout_mode = p.get("donchian__breakout_mode", p.get("donchian_breakout_mode", self._breakout_mode))
        self._trailing_stop_pct = float(p.get("donchian__trailing_stop_pct", p.get("donchian_trailing_stop_pct", self._trailing_stop_pct)))
        self._max_position_pct = float(p.get("risk__max_position_pct", p.get("risk_max_position_pct", self._max_position_pct)))

        log.info(
            f"[{self.name}] period={self._period} bars "
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

        # `period` is a number of BARS, not days. It used to be multiplied by
        # bars_per_day, which at the 1m preset of 80 asked for 80 x 270 =
        # 21,600 bars -- about eighty trading days -- so the guard below was
        # still true after six months of 1m data and this strategy returned
        # early on every bar of every run. The preset values (1m 80, 5m 12,
        # 1h 18, 1d 20) only make sense as bars, and adx.py already reads the
        # same number that way.
        prices = ctx.prices(symbol)

        # The channel must EXCLUDE the current bar. price_history already has
        # this bar's close appended by the time on_bar is called, so a window
        # of prices[-period:] contains `close` itself; max() is then >= close
        # and `close > donchian_high` cannot ever be true. Together with the
        # lookback above that is why this strategy recorded zero fills over
        # 18,794 bars. The same off-by-one was fixed in the ADX template
        # earlier with bar.closes[:-1]; this is the strategy it was copied from.
        if len(prices) < self._period + 1:
            self._prev_close[symbol] = close
            return []

        recent_closes = prices[-self._period - 1:-1]
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
                self._peak[symbol] = close
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
        # Check the trailing stop first, measured from the peak since entry.
        if ctx.has_position(symbol) and symbol in self._entry_price:
            entry_price = self._entry_price[symbol]
            peak = max(self._peak.get(symbol, entry_price), close)
            self._peak[symbol] = peak
            trailing_stop_level = peak * (1 - self._trailing_stop_pct)

            if self._trailing_stop_pct > 0 and close < trailing_stop_level:
                qty = ctx.position_qty(symbol)
                log.info(
                    f"ts: {ts_str} | SELL {symbol} @ {close:.2f} "
                    f"* {qty} shares (trailing stop {self._trailing_stop_pct*100:.2f}% "
                    f"below peak {peak:.2f}, entry was {entry_price:.2f})"
                )
                signals.append(Signal(
                    action="SELL",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=(f"Trailing stop: {close:.2f} is more than "
                            f"{self._trailing_stop_pct*100:.2f}% below the "
                            f"peak of {peak:.2f}"),
                    meta={"stop_type": "trailing", "peak": peak}
                ))
                del self._entry_price[symbol]
                self._peak.pop(symbol, None)
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
            self._peak.pop(symbol, None)

        # Store state
        self._prev_close[symbol] = close
        return signals

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Called after a fill is executed."""
        log.info(f"[{self.name}] {fill.action} {fill.quantity} @ {fill.price} ({fill.symbol})")

    def on_end(self, ctx: StrategyContext) -> None:
        """Called at end of backtest."""
        log.info(f"[{self.name}] Backtest completed")
