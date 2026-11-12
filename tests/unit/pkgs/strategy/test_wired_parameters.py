"""
tests/unit/pkgs/strategy/test_wired_parameters.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A parameter the presets advertise must change the run.

Every case here covers a knob that was shipped by `INTERVAL_PRESETS`, accepted
without complaint, and then read by nobody. That failure mode is quiet in the
worst way for a parameter search: the search explores the axis, measures no
gradient, and reports that the parameter does not matter -- which is
indistinguishable from the parameter not being connected.

Measured before the fix, over 18,794 real 1m bars of 2357:

    bb__std_dev             2.0 -> 5.0    identical fills AND equity
    dca__max_position_pct   0.03 -> 0.075 identical
    dca__buy_frequency_days 1 -> 2        identical (superseded key)
    donchian__period        80 -> 160     identical (strategy never traded)
    adx__strong_threshold   30 -> 75      identical (regime unreachable)
    adx__donchian_period    80 -> 160     identical (regime unreachable)

So these tests assert on *sensitivity*, not on a golden number. A test pinning
exact fill counts would pass just as happily against a disconnected knob.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.strategy.adx import ADXAdaptiveStrategy
from cjtrade.pkgs.strategy.bb import BollingerStrategy
from cjtrade.pkgs.strategy.base_strategy import StrategyContext
from cjtrade.pkgs.strategy.dca import DCA_Monthly
from cjtrade.pkgs.strategy.donchian import DonchianBreakoutStrategy
from cjtrade.pkgs.strategy.parameters.manager import ParameterManager
from cjtrade.pkgs.strategy.parameters.presets import INTERVAL_PRESETS
from cjtrade.pkgs.strategy.parameters.schema import PARAM_SCHEMA

SYM = "T"
CASH = 1_000_000.0


def bars(closes, start=datetime(2025, 1, 2, 9, 1)):
    return [Kbar(timestamp=start + timedelta(minutes=i), open=c, high=c,
                 low=c, close=c, volume=1000, symbol=SYM)
            for i, c in enumerate(closes)]


def wave(n=4000, period=120, amplitude=4.0, base=100.0):
    """A deterministic oscillation. Mean-reverting enough for Bollinger to
    trade and with enough local extremes for a channel to be broken."""
    import math
    return [base + amplitude * math.sin(2 * math.pi * i / period)
            + 0.6 * math.sin(2 * math.pi * i / 17)
            for i in range(n)]


def run(cls, closes, params, **kw):
    result = BacktestEngine(kbars=bars(closes), initial_balance=CASH,
                            params=params, session_id="t", **kw).run(cls())
    return len(result.fill_history), round(result.final_equity, 2)


def ctx(ts, prices, params, equity=CASH, positions=None):
    return StrategyContext(timestamp=ts, balance=equity, equity=equity,
                           positions=positions or [],
                           price_history={SYM: list(prices)},
                           bar_index=len(prices), params=params)


# ══════════════════════════════════════════════════════════════════════════
#  Bollinger: bb__std_dev
# ══════════════════════════════════════════════════════════════════════════

def test_bb_std_dev_changes_the_run():
    """ta.bb() was called with a literal 2, so this did nothing at all."""
    closes = wave()
    tight = run(BollingerStrategy, closes,
                {"bb__window_size": 100, "bb__std_dev": 1.0,
                 "bb__min_width_pct": 0.0, "risk__max_position_pct": 0.1})
    wide = run(BollingerStrategy, closes,
               {"bb__window_size": 100, "bb__std_dev": 3.0,
                "bb__min_width_pct": 0.0, "risk__max_position_pct": 0.1})
    assert tight != wide


def test_bb_wider_bands_trade_less_often():
    """Direction, not just sensitivity: bands further from the mean are
    touched less, so a larger multiplier must not trade more."""
    closes = wave()
    counts = [run(BollingerStrategy, closes,
                  {"bb__window_size": 100, "bb__std_dev": sd,
                   "bb__min_width_pct": 0.0, "risk__max_position_pct": 0.1})[0]
              for sd in (1.0, 2.0, 3.0)]
    assert counts == sorted(counts, reverse=True), counts
    assert counts[0] > counts[-1]


def test_bb_std_dev_widens_the_bands_it_reports():
    """Checks the bands themselves, not just that the run moved: the
    multiplier has to reach ta.bb(), and `bandwidth_pct` is what it produced."""
    closes = wave(600)
    bandwidth = {}
    for std in (1.0, 3.0):
        params = {"bb__window_size": 100, "bb__std_dev": std,
                  "bb__min_width_pct": 0.0, "risk__max_position_pct": 0.1}
        strategy = BollingerStrategy()
        strategy.on_start(ctx(datetime(2025, 1, 2), [], params))
        for i, bar in enumerate(bars(closes)):
            strategy.on_bar(bar, ctx(bar.timestamp, closes[:i + 1], params))
        bandwidth[std] = strategy.monitors()["bandwidth_pct"]
    # Three sigma spans three times what one sigma does on the same data.
    assert bandwidth[3.0] == pytest.approx(bandwidth[1.0] * 3, rel=0.01)


def test_bb_std_dev_override_is_not_dropped_by_the_parameter_manager():
    """It was marked `fixed`, which made ParameterManager discard overrides
    (manager.py:109) -- a second, independent reason the knob did nothing."""
    cfg = ParameterManager.load_params(
        interval="1m", strategy_name="BollingerBands",
        user_overrides={"bb__std_dev": 2.5})
    assert cfg.params["bb__std_dev"] == 2.5


def test_no_tunable_parameter_is_marked_fixed_by_accident():
    """`fixed` silently discards user overrides, so it belongs only on values
    derived from the interval -- not on anything worth sweeping."""
    fixed = {k for k, v in PARAM_SCHEMA.items() if v.get("fixed")}
    assert fixed <= {"sr__interval"}, f"unexpectedly un-overridable: {fixed}"


# ══════════════════════════════════════════════════════════════════════════
#  DCA: instalment sizing and cadence
# ══════════════════════════════════════════════════════════════════════════

def test_dca_max_position_pct_sizes_the_instalment():
    """The presets ship this and only this; the strategy read dca__amount."""
    strategy = DCA_Monthly()
    params = {"dca__max_position_pct": 0.10}
    strategy.on_start(ctx(datetime(2026, 1, 1), [], params))
    bar = Kbar(timestamp=datetime(2026, 1, 5, 9, 1), open=50.0, high=50.0,
               low=50.0, close=50.0, volume=1, symbol=SYM)
    signals = strategy.on_bar(bar, ctx(bar.timestamp, [50.0], params,
                                       equity=1_000_000.0))
    assert signals
    # 10% of 1,000,000 = 100,000, at 50 a share.
    assert signals[0].quantity == 2000


def test_dca_pct_scales_with_equity_where_a_fixed_amount_cannot():
    params = {"dca__max_position_pct": 0.10}
    quantities = []
    for equity in (500_000.0, 1_000_000.0):
        strategy = DCA_Monthly()
        strategy.on_start(ctx(datetime(2026, 1, 1), [], params))
        bar = Kbar(timestamp=datetime(2026, 1, 5, 9, 1), open=50.0, high=50.0,
                   low=50.0, close=50.0, volume=1, symbol=SYM)
        sig = strategy.on_bar(bar, ctx(bar.timestamp, [50.0], params,
                                       equity=equity))
        quantities.append(sig[0].quantity)
    assert quantities == [1000, 2000]


def test_dca_amount_still_works_when_no_pct_is_given():
    """Backward compatibility: a config that only sets dca__amount is
    unchanged by the new sizing mode."""
    strategy = DCA_Monthly()
    params = {"dca__amount": 10_000.0}
    strategy.on_start(ctx(datetime(2026, 1, 1), [], params))
    bar = Kbar(timestamp=datetime(2026, 1, 5, 9, 1), open=50.0, high=50.0,
               low=50.0, close=50.0, volume=1, symbol=SYM)
    sig = strategy.on_bar(bar, ctx(bar.timestamp, [50.0], params))
    assert sig[0].quantity == 200


def test_dca_buy_frequency_months_skips_months():
    """A quarterly plan buys in Jan and Apr, not every month."""
    params = {"dca__amount": 10_000.0, "dca__buy_frequency_months": 3}
    strategy = DCA_Monthly()
    strategy.on_start(ctx(datetime(2026, 1, 1), [], params))
    bought = []
    for month in range(1, 8):
        ts = datetime(2026, month, 5, 9, 1)
        bar = Kbar(timestamp=ts, open=50.0, high=50.0, low=50.0, close=50.0,
                   volume=1, symbol=SYM)
        if strategy.on_bar(bar, ctx(ts, [50.0], params)):
            bought.append(month)
    assert bought == [1, 4, 7]


def test_dca_default_cadence_is_every_month():
    params = {"dca__amount": 10_000.0}
    strategy = DCA_Monthly()
    strategy.on_start(ctx(datetime(2026, 1, 1), [], params))
    bought = []
    for month in range(1, 6):
        ts = datetime(2026, month, 5, 9, 1)
        bar = Kbar(timestamp=ts, open=50.0, high=50.0, low=50.0, close=50.0,
                   volume=1, symbol=SYM)
        if strategy.on_bar(bar, ctx(ts, [50.0], params)):
            bought.append(month)
    assert bought == [1, 2, 3, 4, 5]


def test_dca_superseded_days_key_warns_rather_than_being_ignored(caplog):
    """The drifting day-count was deliberately replaced by calendar months, so
    this key stays unwired -- but it must say so instead of silently doing
    nothing for a third time."""
    strategy = DCA_Monthly()
    with caplog.at_level("WARNING"):
        strategy.on_start(ctx(datetime(2026, 1, 1), [],
                              {"dca__buy_frequency_days": 30}))
    assert "dca__buy_frequency_months" in caplog.text


def test_presets_no_longer_advertise_the_unwired_dca_key():
    for interval, preset in INTERVAL_PRESETS.items():
        assert "dca__buy_frequency_days" not in preset, interval
        assert preset["dca__buy_frequency_months"] >= 1, interval


# ══════════════════════════════════════════════════════════════════════════
#  Donchian: the channel excluded its own bar, and the lookback was in days
# ══════════════════════════════════════════════════════════════════════════

def test_donchian_breaks_out_of_a_flat_channel():
    """Six flat bars then a higher one. With the current bar inside its own
    channel, max() >= close and `close > high` was unsatisfiable."""
    _, _ = None, None
    result = BacktestEngine(
        kbars=bars([100.0] * 6 + [101.0] + [100.5] * 3),
        initial_balance=CASH, session_id="d",
        params={"donchian__period": 5, "risk__max_position_pct": 0.5,
                "donchian__trailing_stop_pct": 0.0},
    ).run(DonchianBreakoutStrategy())
    buys = [f for f in result.fill_history if f["action"] == "BUY"]
    assert buys, "no breakout at all"
    assert buys[0]["price"] == 101.0


def test_donchian_period_counts_bars_not_days():
    """It was multiplied by bars_per_day (270 at 1m), so the 1m preset of 80
    demanded 21,600 bars and the strategy returned early on every bar of a
    six-month run."""
    closes = [100.0] * 30 + [101.0] + [100.5] * 10
    result = BacktestEngine(
        kbars=bars(closes), initial_balance=CASH, session_id="d",
        params={"donchian__period": 20, "risk__max_position_pct": 0.5,
                "donchian__trailing_stop_pct": 0.0},
    ).run(DonchianBreakoutStrategy())
    # 41 bars is far fewer than 20 days' worth, but it is more than 20 bars.
    assert result.fill_history


def test_donchian_trades_on_a_realistic_series():
    """The whole-run regression: zero fills over 18,794 real bars."""
    fills, _ = run(DonchianBreakoutStrategy, wave(),
                   {"donchian__period": 80, "risk__max_position_pct": 0.2,
                    "donchian__trailing_stop_pct": 0.015})
    assert fills > 0


def test_donchian_period_changes_the_run():
    closes = wave()
    short = run(DonchianBreakoutStrategy, closes,
                {"donchian__period": 40, "risk__max_position_pct": 0.2,
                 "donchian__trailing_stop_pct": 0.0})
    long = run(DonchianBreakoutStrategy, closes,
               {"donchian__period": 160, "risk__max_position_pct": 0.2,
                "donchian__trailing_stop_pct": 0.0})
    assert short != long


def test_donchian_stop_trails_the_peak_not_the_entry():
    """Enter at 101, run to 110, then slip 2% off the peak. A stop measured
    from the entry price would need 98.98 and could never fire here -- which
    is what `entry_price * (1 - pct)` computed."""
    result = BacktestEngine(
        kbars=bars([100.0] * 6 + [101.0, 103.0, 105.0, 107.0, 110.0,
                                 109.0, 108.0, 107.5, 107.0]),
        initial_balance=CASH, session_id="d",
        params={"donchian__period": 5, "risk__max_position_pct": 0.5,
                "donchian__trailing_stop_pct": 0.02},
    ).run(DonchianBreakoutStrategy())
    sells = [f for f in result.fill_history if f["action"] == "SELL"]
    assert sells, "the trailing stop never fired"
    assert sells[0]["price"] > 101.0, "sold below entry: still not trailing"
    assert sells[0]["price"] == pytest.approx(107.5)


def test_donchian_trailing_stop_pct_changes_the_run():
    closes = wave()
    assert run(DonchianBreakoutStrategy, closes,
               {"donchian__period": 80, "risk__max_position_pct": 0.2,
                "donchian__trailing_stop_pct": 0.005}) \
        != run(DonchianBreakoutStrategy, closes,
               {"donchian__period": 80, "risk__max_position_pct": 0.2,
                "donchian__trailing_stop_pct": 0.05})


# ══════════════════════════════════════════════════════════════════════════
#  ADX: the trend regime's channel had the same off-by-one
# ══════════════════════════════════════════════════════════════════════════

def test_adx_donchian_period_changes_the_run():
    """Inert before: the TREND branch owns the Donchian logic, and its channel
    included the current bar, so the breakout inside it could never fire."""
    closes = wave()
    base = {"adx__period": 25, "adx__strong_threshold": 30.0,
            "adx__weak_threshold": 15.0, "adx__snr_lookback_days": 3,
            "adx__snr_threshold_pct": 0.008, "risk__max_position_pct": 0.1,
            "adx__interval": "1m"}
    assert run(ADXAdaptiveStrategy, closes, {**base, "adx__donchian_period": 40}) \
        != run(ADXAdaptiveStrategy, closes, {**base, "adx__donchian_period": 160})


def test_adx_strong_threshold_changes_the_run():
    closes = wave()
    base = {"adx__period": 25, "adx__weak_threshold": 15.0,
            "adx__donchian_period": 80, "adx__snr_lookback_days": 3,
            "adx__snr_threshold_pct": 0.008, "risk__max_position_pct": 0.1,
            "adx__interval": "1m"}
    assert run(ADXAdaptiveStrategy, closes, {**base, "adx__strong_threshold": 25.0}) \
        != run(ADXAdaptiveStrategy, closes, {**base, "adx__strong_threshold": 80.0})


def test_adx_reaches_its_trend_regime_and_trades_inside_it():
    """`bars_trend` is the direct evidence, and it is what made the two knobs
    above measure as inert: a regime nothing enters has no parameters.

    Asserted on the counter rather than on fill counts so the test names the
    cause. A run can produce fills from the other two regimes while TREND
    stays at zero, which is exactly the state this replaced.
    """
    params = {"adx__period": 25, "adx__strong_threshold": 30.0,
              "adx__weak_threshold": 15.0, "adx__donchian_period": 80,
              "adx__snr_lookback_days": 3, "adx__snr_threshold_pct": 0.008,
              "risk__max_position_pct": 0.1, "adx__interval": "1m"}
    closes = wave()
    strategy = ADXAdaptiveStrategy()
    strategy.on_start(ctx(datetime(2025, 1, 2), [], params))
    signals = 0
    for i, bar in enumerate(bars(closes)):
        signals += len(strategy.on_bar(
            bar, ctx(bar.timestamp, closes[:i + 1], params)) or [])
    mon = strategy.monitors()
    assert mon["bars_trend"] > 0, "the TREND regime is still unreachable"
    assert signals > 0
    # All three regimes should be visited on an oscillating series; a strategy
    # that only ever sees one is not adaptive whatever the thresholds say.
    assert mon["bars_consolidation"] > 0
    assert mon["bars_neutral"] > 0
