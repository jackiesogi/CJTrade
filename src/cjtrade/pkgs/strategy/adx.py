"""
pkgs/strategy/custom.py
~~~~~~~~~~~~~~~~~~~~~~~
ADX-based Adaptive Strategy: Donchian Breakout in trends + SNR in consolidation.

Behavior
--------
- Calculates ADX (Average Directional Index) to detect trend strength
- Splits into 3 regimes:
  * Strong Trend (ADX > adx_strong_threshold, e.g. 40): Donchian breakout
  * Consolidation (ADX < adx_weak_threshold, e.g. 20): Support & Resistance
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
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Tuple

import numpy
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
            f"[{self.name}] ADX_period={self._adx_period} "
            f"strong_threshold={self._adx_strong_threshold} "
            f"weak_threshold={self._adx_weak_threshold} "
            f"donchian_period={self._donchian_period} "
            f"snr_lookback_days={self._snr_lookback_days}"
        )

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        """Process incoming bar and generate signals."""
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
            return []

        # Calculate ADX
        adx_value = self._calculate_adx(bar, ctx)

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

        # Store state
        self._prev_close[symbol] = close
        self._prev_high[symbol] = high
        self._prev_low[symbol] = low

        if signal:
            signal.meta["regime"] = regime
            signal.meta["adx"] = adx_value
            return [signal]

        return []

    def _calculate_adx(self, bar, ctx: StrategyContext) -> float:
        """Calculate ADX (Average Directional Index)."""
        symbol = bar.symbol
        prices = ctx.prices(symbol)

        if len(prices) < self._adx_period + 5:
            return 20.0  # Default neutral value

        # We need highs/lows too, but we'll approximate from close prices
        # A better implementation would track all highs/lows in price_history
        try:
            # Simplified ADX: use close price momentum
            # A proper implementation would need full OHLC history
            recent = prices[-self._adx_period:]
            momentum = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]

            # ADX as smoothed absolute momentum (vibes of trend strength)
            abs_momentum = [abs(m) for m in momentum]
            adx_approx = numpy.mean(abs_momentum) * 100  # Scale to 0-100 range
            adx_approx = min(100, max(0, adx_approx))  # Clamp

            return adx_approx
        except Exception as e:
            log.warning(f"[{self.name}] ADX calculation failed: {e}, using default")
            return 20.0

    def _donchian_logic(self, bar: dict, ctx: StrategyContext, symbol: str, close: float) -> Signal | None:
        """Donchian breakout in strong trends: BUY on breakout above high, SELL below low."""
        prices = ctx.prices(symbol)

        if len(prices) < self._donchian_period:
            return None

        # Get Donchian high and low
        recent_closes = prices[-self._donchian_period:]
        donchian_high = max(recent_closes)
        donchian_low = min(recent_closes)

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
        if ctx.has_position(symbol):
            prices = ctx.prices(symbol)
            if len(prices) >= 10:
                recent = prices[-10:]
                recent_high = max(recent)
                recent_low = min(recent)

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
