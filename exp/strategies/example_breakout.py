"""Worked example: a daily-horizon breakout on 1m bars, flat most of the time.

Shown because it is the shape the experiment needs and the built-ins cannot
express: the signal is computed over a multi-day window (`lookback` in BARS --
270 bars is one trading day), the position is held for days, and the strategy
is in cash unless price is making new highs.

It is a STARTING POINT, not a candidate. Nothing here is tuned.

Run it:
    ARENAX_PORT=8802 uv run python exp/bin/custom_backtest.py \
        --file exp/strategies/example_breakout.py \
        --symbol 2317 --start 2021-01-01 --duration 1461 --interval 1m \
        --params 'lookback:5400,exit_lookback:2700,pos_pct:0.5'
"""
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Signal

BARS_PER_DAY = 270  # 09:01–13:30 inclusive


class ExampleBreakout(BaseStrategy):
    name = "ExampleBreakout"

    def on_start(self, ctx):
        self.entry_price = None
        self._reasons = {}

    def on_bar(self, bar, ctx):
        p = ctx.params
        lookback = int(p.get("lookback", 20 * BARS_PER_DAY))
        exit_lookback = int(p.get("exit_lookback", 10 * BARS_PER_DAY))
        pos_pct = float(p.get("pos_pct", 0.5))
        stop_pct = float(p.get("stop_pct", 0.0))

        closes = ctx.prices(bar.symbol)
        if len(closes) < lookback + 1:
            self._reasons = {"state": "warming_up", "bars": len(closes)}
            return []

        # Exclude the current bar from both channels, or a new high is
        # tautologically also the highest of the window that contains it.
        window = closes[-(lookback + 1):-1]
        high = max(window)
        low = min(closes[-(exit_lookback + 1):-1])
        holding = ctx.has_position(bar.symbol)
        self._reasons = {"state": "holding" if holding else "flat",
                         "high": round(high, 2), "low": round(low, 2)}

        if not holding:
            if bar.close > high:
                qty = int(ctx.equity * pos_pct / bar.close)
                if qty > 0:
                    self.entry_price = bar.close
                    return [Signal("BUY", bar.symbol, qty, bar.close,
                                   reason=f"close {bar.close:.2f} > {lookback}-bar high {high:.2f}")]
            return []

        qty = ctx.position_qty(bar.symbol)
        if stop_pct > 0 and self.entry_price and bar.close <= self.entry_price * (1 - stop_pct):
            return [Signal("SELL", bar.symbol, qty, bar.close,
                           reason=f"stop: {bar.close:.2f} <= entry {self.entry_price:.2f} -{stop_pct:.1%}")]
        if bar.close < low:
            return [Signal("SELL", bar.symbol, qty, bar.close,
                           reason=f"close {bar.close:.2f} < {exit_lookback}-bar low {low:.2f}")]
        return []

    def monitors(self):
        return self._reasons
