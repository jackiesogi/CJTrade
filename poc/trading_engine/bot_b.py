"""
poc/trading_engine/bot_b.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ADX-gated regime switching: Donchian breakout while a trend holds, support and
resistance while the price ranges.

Everything that is not the strategy choice lives in bot_runner.py.

Know what you are running: the regime is chosen by an efficiency ratio (net
move over total path, 0-100), not the Wilder ADX. A real ADX needs each bar's
own high and low, and this feed does not carry them -- the Snapshot's high and
low are the trading day's so far, not the bar's. The thresholds below are the
conventional ADX ones and they do transfer, because the efficiency ratio is
scale-free; see adx.py's _calculate_adx for the measurement that establishes
that.
"""
from bot_runner import run_bot
from cjtrade.pkgs.strategy.adx import ADXAdaptiveStrategy

SYMBOL = "2357"

PARAMS = {
    "adx__period": 14,
    "adx__strong_threshold": 40.0,
    "adx__weak_threshold": 20.0,
    "adx__donchian_period": 20,
    # In days, multiplied by bars-per-day inside the strategy. 20 days of 1m
    # bars is 5,400 points, which this bot will not have until late in a long
    # run; until then the strategy falls back to however much history it has.
    "adx__snr_lookback_days": 20,
    "adx__snr_threshold_pct": 0.01,
    # Same reasoning as bot_c: 0.05 of a small account sizes an order that pays
    # the NT$20 commission floor instead of the 0.1425% rate.
    "risk__max_position_pct": 0.20,
    # Tells the strategy how many bars make a day, for the S/R lookback above.
    "adx__interval": "1m",
}


if __name__ == "__main__":
    run_bot(ADXAdaptiveStrategy(), SYMBOL, PARAMS)
