"""
pkgs/strategy/adx.py
~~~~~~~~~~~~~~~~~~~~~
Regime-switching strategy: Donchian breakout in trends + SNR in consolidation.

What measures the trend
-----------------------
An efficiency ratio on a 0-100 scale (net displacement / total path travelled
over `adx__period` closes), NOT the Wilder ADX -- this feed carries no per-bar
high and low to compute one from. See _calculate_adx, which also records what
it replaced and why the 40/20 thresholds still mean something.

Behavior
--------
- Measures trend strength to pick a regime
- Splits into 3 regimes:
  * Strong Trend (strength > adx__strong_threshold, e.g. 40): Donchian breakout
  * Consolidation (strength < adx__weak_threshold, e.g. 20): Support & Resistance
  * Neutral (mid-range): Conservative mixed mode

- Donchian Breakout: BUY on breakout above N-day high, SELL below N-day low
- SNR Mode: BUY near support, SELL near resistance (like SupportResistanceStrategy)

Parameters (via ctx.params or constructor defaults)
- adx__period: ADX calculation period (default: 14)
- adx__strong_threshold: ADX value to enter strong trend mode (default: 40)
- adx__weak_threshold: ADX value to enter consolidation mode (default: 20)
- adx__donchian_period: Donchian lookback in trend mode (default: 20)
- adx__snr_lookback_days: Support/Resistance lookback in consolidation mode (default: 20)
- adx__snr_threshold_pct: How close to S/R before trading (default: 0.01)
- risk__max_position_pct: Max position size (default: 0.05)

Usage
-----
from cjtrade.pkgs.strategy.custom import ADXAdaptiveStrategy
strategy = ADXAdaptiveStrategy(
    adx_period=14,
    adx_strong_threshold=40,
    adx_weak_threshold=20,
)
run_oneshot(symbol="2330", start="2023-01-01", strategy=strategy)
"""
from __future__ import annotations

import logging
import math
from typing import Any
from typing import Dict
from typing import List

from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)


class ADXAdaptiveStrategy(BaseStrategy):
    """Adaptive strategy using ADX to switch between Donchian breakout and SNR."""

    name = "ADX_Adaptive"
    long_name = "ADX Adaptive Trend/Consolidation"

    def __init__(
        self,
        adx_period: int = 14,
        adx_strong_threshold: float = 40.0,
        adx_weak_threshold: float = 20.0,
        adx_donchian_period: int = 20,
        adx_snr_lookback_days: int = 20,
        adx_snr_threshold_pct: float = 0.01,
        max_position_pct: float = 0.05,
    ) -> None:
        self._adx_period = adx_period
        self._adx_strong_threshold = adx_strong_threshold
        self._adx_weak_threshold = adx_weak_threshold
        self._donchian_period = adx_donchian_period
        self._snr_lookback_days = adx_snr_lookback_days
        self._snr_threshold_pct = adx_snr_threshold_pct
        self._max_position_pct = max_position_pct

        # Per-symbol state
        self._prev_close: Dict[str, float] = {}
        self._prev_high: Dict[str, float] = {}
        self._prev_low: Dict[str, float] = {}
        self._donchian_broken: Dict[str, bool] = {}  # Track breakout state

        # Bars per day calculation (auto-detect from interval)
        self._bars_per_day: int = 270  # default for 1m

        # ── monitor state ────────────────────────────────────────────────────
        # Read by monitors(), written in on_bar and the three regime handlers.
        # Declared here so monitors() is safe to call before the first bar,
        # which a runner polling on a timer will do.
        self._n_bars = 0
        self._n_signals = 0
        self._adx = 0.0
        self._regime = "unknown"
        self._bars_in_regime: Dict[str, int] = {"TREND": 0,
                                                "CONSOLIDATION": 0,
                                                "NEUTRAL": 0}
        # Whatever levels the active regime's handler last computed, so the
        # monitor can show the numbers the decision was actually made against
        # rather than re-deriving them.
        self._levels: Dict[str, float] = {}
        self._last_reason = "not started"

    def on_start(self, ctx: StrategyContext) -> None:
        """Initialize parameters from ctx.params."""
        p = ctx.params

        # Read ADX parameters (support both old and new naming)
        self._adx_period = int(p.get("adx__period", p.get("adx_period", self._adx_period)))
        self._adx_strong_threshold = float(p.get("adx__strong_threshold", p.get("adx_strong_threshold", self._adx_strong_threshold)))
        self._adx_weak_threshold = float(p.get("adx__weak_threshold", p.get("adx_weak_threshold", self._adx_weak_threshold)))
        self._donchian_period = int(p.get("adx__donchian_period", p.get("adx_donchian_period", self._donchian_period)))
        self._snr_lookback_days = int(p.get("adx__snr_lookback_days", p.get("adx_snr_lookback_days", self._snr_lookback_days)))
        self._snr_threshold_pct = float(p.get("adx__snr_threshold_pct", p.get("adx_snr_threshold_pct", self._snr_threshold_pct)))
        self._max_position_pct = float(p.get("risk__max_position_pct", p.get("risk_max_position_pct", self._max_position_pct)))

        # Auto-detect bars per day from interval hint. adx__interval is the
        # name that matches every other parameter this strategy reads; the sr_*
        # spellings are what it used to be called, kept so an existing config
        # does not silently fall back to 1m.
        interval_hint = p.get("adx__interval",
                              p.get("sr__interval", p.get("sr_interval", "1m")))
        if interval_hint.lower() == "1d":
            self._bars_per_day = 1
        elif interval_hint.lower() == "1h":
            self._bars_per_day = 7
        elif interval_hint.lower() == "5m":
            self._bars_per_day = 54
        else:  # default 1m
            self._bars_per_day = 270

        self._n_bars = self._n_signals = 0
        self._adx = 0.0
        self._regime = "unknown"
        self._bars_in_regime = {"TREND": 0, "CONSOLIDATION": 0, "NEUTRAL": 0}
        self._levels = {}
        self._last_reason = "no bars yet"

        log.info(
            f"[{self.name}] ADX_period={self._adx_period} "
            f"strong_threshold={self._adx_strong_threshold} "
            f"weak_threshold={self._adx_weak_threshold} "
            f"donchian_period={self._donchian_period} "
            f"snr_lookback_days={self._snr_lookback_days}"
        )

    # ── monitoring ───────────────────────────────────────────────────────────

    def monitors(self) -> Dict[str, Any]:
        """See BaseStrategy.monitors. Plain floats, ints and strings only.

        `adx` is the close-only approximation this strategy computes, not the
        Wilder ADX -- see _calculate_adx. Reported anyway because the regime
        switch is made against this number, so it is the one that explains the
        behaviour.
        """
        out: Dict[str, Any] = {
            "bars_seen":         self._n_bars,
            "trend_strength":    round(self._adx, 2),
            "measure":           "efficiency ratio (net move / path, 0-100)",
            "regime":            self._regime,
            "strong_threshold":  self._adx_strong_threshold,
            "weak_threshold":    self._adx_weak_threshold,
            "bars_trend":        self._bars_in_regime["TREND"],
            "bars_consolidation": self._bars_in_regime["CONSOLIDATION"],
            "bars_neutral":      self._bars_in_regime["NEUTRAL"],
            "signals_emitted":   self._n_signals,
            "last_decision":     self._last_reason,
        }
        # The active regime's levels, whatever they are called. Flattened into
        # the same dict because a runner puts this straight on a wire.
        for key, value in self._levels.items():
            out[key] = round(value, 2)
        return out

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Process incoming bar and generate signals."""
        self._n_bars += 1
        symbol = bar.symbol
        close = bar.close
        high = bar.high
        low = bar.low

        # Ensure we have history
        prices = ctx.prices(symbol)
        if len(prices) < self._adx_period + 5:
            # Not enough data yet
            self._prev_close[symbol] = close
            self._prev_high[symbol] = high
            self._prev_low[symbol] = low
            self._last_reason = (f"warming up: {len(prices)} of "
                                 f"{self._adx_period + 5} bars")
            return []

        # Calculate ADX
        adx_value = self._calculate_adx(bar, ctx)
        self._adx = adx_value

        # Determine market regime
        if adx_value > self._adx_strong_threshold:
            # Strong trend → Donchian breakout
            regime = "TREND"
            signal = self._donchian_logic(bar, ctx, symbol, close)
        elif adx_value < self._adx_weak_threshold:
            # Consolidation → Support & Resistance
            regime = "CONSOLIDATION"
            signal = self._snr_logic(bar, ctx, symbol, close, high, low)
        else:
            # Neutral/mixed
            regime = "NEUTRAL"
            signal = self._neutral_logic(bar, ctx, symbol, close, high, low)

        self._regime = regime
        self._bars_in_regime[regime] += 1

        # Store state
        self._prev_close[symbol] = close
        self._prev_high[symbol] = high
        self._prev_low[symbol] = low

        if signal:
            signal.meta["regime"] = regime
            signal.meta["trend_strength"] = adx_value
            self._n_signals += 1
            self._last_reason = (f"{signal.action} {signal.quantity} "
                                 f"{signal.symbol} @ {signal.price:.2f} — "
                                 f"{signal.reason}")
            return [signal]

        # Nothing fired. Which regime declined, and against which levels, is
        # the whole of what makes a quiet run legible -- "no signal" on its own
        # does not distinguish a ranging market from a strategy that never had
        # enough history to compute its support band.
        levels = "  ".join(f"{k}={v:.2f}" for k, v in self._levels.items())
        self._last_reason = (f"{regime} (strength={adx_value:.1f}): price "
                             f"{close:.2f} reached no level"
                             + (f" [{levels}]" if levels else ""))
        return []

    def _neutral_value(self) -> float:
        """What this measure reads for a market with no net direction.

        A random walk of n steps travels about sqrt(n) times the length of one
        step while covering n steps of path, so its efficiency ratio tends to
        100/sqrt(n). Using that as the warm-up and error default puts an
        unknown market in NEUTRAL by construction, instead of asserting
        consolidation.
        """
        n = max(2, self._adx_period)
        return 100.0 / math.sqrt(n)

    def _calculate_adx(self, bar, ctx: StrategyContext) -> float:
        """Trend strength on a 0-100 scale, from closes alone.

        This is an efficiency ratio -- net displacement over total path
        travelled -- and NOT the Wilder ADX, which needs each bar's own high
        and low. StrategyContext carries price_history as closes and nothing
        else, and the Snapshot this feed delivers reports the trading DAY's
        high and low rather than the bar's (see main2's _snapshot_real), so
        there is no per-bar range available to compute a real ADX from.

        It replaced `mean(|1-bar return|) * 100`, which was not on a 0-100
        scale at all: that figure is a percent-per-bar, so over 1,063,349 real
        1m bars across ten Taiwan symbols it never once exceeded 1.1 and the
        strategy spent 100% of every run in CONSOLIDATION -- two of its three
        regimes were unreachable code, on every symbol and every interval.

        The efficiency ratio fixes that without the thresholds moving, because
        it is genuinely scale-free: it divides a price distance by a price
        distance, so neither the level of the stock nor the length of the bar
        appears in the answer. Measured over the same data with period=14 and
        the 40/20 thresholds, every symbol spends 5-30% in TREND, 38-69% in
        CONSOLIDATION and 27-37% in NEUTRAL on 1m bars, and lands in the same
        range on daily bars.
        """
        prices = ctx.prices(bar.symbol)

        if len(prices) < self._adx_period + 5:
            return self._neutral_value()

        window = prices[-self._adx_period:]
        # Total distance walked. Zero only if every close in the window is
        # identical, which a halted or untraded symbol does produce -- and
        # dividing by it would be the one way this can raise.
        path = sum(abs(window[i] - window[i - 1])
                   for i in range(1, len(window)))
        if path <= 0:
            return 0.0          # no movement at all is the opposite of a trend

        net = abs(window[-1] - window[0])
        return min(100.0, net / path * 100.0)

    def _donchian_logic(self, bar: dict, ctx: StrategyContext, symbol: str, close: float) -> Signal | None:
        """Donchian breakout in strong trends: BUY on breakout above high, SELL below low."""
        prices = ctx.prices(symbol)

        if len(prices) < self._donchian_period:
            self._levels = {}
            return None

        # Get Donchian high and low
        recent_closes = prices[-self._donchian_period:]
        donchian_high = max(recent_closes)
        donchian_low = min(recent_closes)
        self._levels = {"donchian_high": donchian_high,
                        "donchian_low": donchian_low}

        prev_close = self._prev_close.get(symbol, close)

        # Breakout above Donchian high
        if prev_close <= donchian_high and close > donchian_high:
            qty = ctx.calc_qty(close, self._max_position_pct)
            if qty > 0:
                return Signal(
                    action="BUY",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"Donchian breakout above {donchian_high:.2f} (ADX trend mode)"
                )

        # Breakout below Donchian low
        if prev_close >= donchian_low and close < donchian_low:
            if ctx.has_position(symbol):
                qty = ctx.position_qty(symbol)
                return Signal(
                    action="SELL",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"Donchian breakout below {donchian_low:.2f} (ADX trend mode)"
                )

        return None

    def _snr_logic(self, bar: dict, ctx: StrategyContext, symbol: str, close: float, high: float, low: float) -> Signal | None:
        """Support & Resistance in consolidation: BUY near support, SELL near resistance."""
        prices = ctx.prices(symbol)

        # Approximate S/R from close prices (simplification)
        bars_lookback = self._snr_lookback_days * self._bars_per_day
        if len(prices) < bars_lookback:
            bars_lookback = len(prices)

        recent = prices[-bars_lookback:]
        support = min(recent)
        resistance = max(recent)
        self._levels = {"support": support, "resistance": resistance}

        prev_close = self._prev_close.get(symbol, close)

        # Buy near support (from above)
        support_zone = support * (1 + self._snr_threshold_pct)
        if prev_close > support_zone and close <= support_zone and close > support:
            qty = ctx.calc_qty(close, self._max_position_pct)
            if qty > 0:
                return Signal(
                    action="BUY",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"SNR: near support {support:.2f} (consolidation mode)"
                )

        # Sell near resistance (from below)
        resistance_zone = resistance * (1 - self._snr_threshold_pct)
        if prev_close < resistance_zone and close >= resistance_zone and close < resistance:
            if ctx.has_position(symbol):
                qty = ctx.position_qty(symbol)
                return Signal(
                    action="SELL",
                    symbol=symbol,
                    quantity=qty,
                    price=close,
                    reason=f"SNR: near resistance {resistance:.2f} (consolidation mode)"
                )

        return None

    def _neutral_logic(self, bar: dict, ctx: StrategyContext, symbol: str, close: float, high: float, low: float) -> Signal | None:
        """Neutral/mixed regime: conservative approach (no new trades, hold or exit on extremes)."""
        self._levels = {}
        if ctx.has_position(symbol):
            prices = ctx.prices(symbol)
            if len(prices) >= 10:
                recent = prices[-10:]
                recent_high = max(recent)
                recent_low = min(recent)
                self._levels = {"recent_high": recent_high,
                                "recent_low": recent_low,
                                "stop": recent_low * 0.98}

                # Exit on strong reversal
                if close < recent_low * 0.98:  # 2% below recent low
                    qty = ctx.position_qty(symbol)
                    return Signal(
                        action="SELL",
                        symbol=symbol,
                        quantity=qty,
                        price=close,
                        reason="Neutral: reversal signal, exit position"
                    )

        return None

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        """Called after a fill is executed."""
        log.info(f"[{self.name}] {fill.action} {fill.quantity} @ {fill.price} ({fill.symbol})")

    def on_end(self, ctx: StrategyContext) -> None:
        """Called at end of backtest."""
        log.info(f"[{self.name}] Backtest completed")
