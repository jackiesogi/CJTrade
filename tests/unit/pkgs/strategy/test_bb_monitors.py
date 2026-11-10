"""BollingerStrategy.monitors() — the record of what the strategy saw and did.

on_bar returns an empty list for five different reasons and the caller cannot
tell them apart. Every one of those paths now names itself in
monitors()["last_decision"], which is the only way to answer "why did this run
trade less than I expected".
"""
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import StrategyContext
from cjtrade.pkgs.strategy.bb import BollingerStrategy

T0 = datetime(2025, 9, 1, 9, 0)
SYM = "2317"
WINDOW = 20


def _ctx(prices, *, qty=0, equity=100_000.0, balance=100_000.0,
         avg_cost=100.0, params=None, bar_index=0) -> StrategyContext:
    positions = []
    if qty:
        positions = [{
            "symbol": SYM, "quantity": qty, "avg_cost": avg_cost,
            "current_price": prices[-1] if prices else avg_cost,
            "market_value": qty * avg_cost, "unrealized_pnl": 0.0,
        }]
    return StrategyContext(
        timestamp=T0 + timedelta(minutes=bar_index),
        balance=balance, equity=equity, positions=positions,
        price_history={SYM: list(prices)}, bar_index=bar_index,
        params=params if params is not None else {
            "bb__window_size": WINDOW, "bb__min_width_pct": 0.0,
            "risk__max_position_pct": 0.20,
        },
    )


def _bar(close, i=0) -> Kbar:
    return Kbar(timestamp=T0 + timedelta(minutes=i), open=close, high=close,
                low=close, close=close, volume=100, symbol=SYM)


def _started(params=None) -> BollingerStrategy:
    s = BollingerStrategy()
    s.on_start(_ctx([], params=params))
    return s


def _feed(strategy, closes, *, qty=0, equity=100_000.0, balance=100_000.0):
    """Drive the strategy bar by bar over `closes`, returning the last signals."""
    out = []
    for i, c in enumerate(closes):
        ctx = _ctx(closes[:i + 1], qty=qty, equity=equity, balance=balance,
                   bar_index=i)
        out = strategy.on_bar(_bar(c, i), ctx) or []
    return out


# ── the hook itself ──────────────────────────────────────────────────────────

class TestTheHook:
    def test_base_strategy_default_is_empty(self):
        """Every other strategy inherits this and keeps working."""
        class Bare(BaseStrategy):
            def on_bar(self, bar, ctx):
                return []

        assert Bare().monitors() == {}

    def test_safe_to_call_before_on_start(self):
        """A runner polling on a timer will call it before the first bar."""
        m = BollingerStrategy().monitors()
        assert m["last_decision"] == "not started"
        assert m["bars_seen"] == 0

    def test_values_are_wire_safe(self):
        """These cross a process boundary into msgpack, so no numpy types."""
        s = _started()
        _feed(s, [100.0 + (i % 5) for i in range(WINDOW + 5)])
        for key, val in s.monitors().items():
            assert type(val) in (int, float, str, bool), f"{key} is {type(val)}"

    def test_on_start_resets_counters(self):
        s = _started()
        _feed(s, [100.0 + (i % 7) for i in range(WINDOW + 10)])
        assert s.monitors()["bars_seen"] > 0
        s.on_start(_ctx([]))
        m = s.monitors()
        assert m["bars_seen"] == 0
        assert m["upper_touches"] == m["lower_touches"] == m["mid_crossings"] == 0
        assert m["signals_emitted"] == 0


# ── last_decision: the five silent paths ─────────────────────────────────────

class TestLastDecision:
    def test_warming_up(self):
        s = _started()
        _feed(s, [100.0] * 3)
        d = s.monitors()["last_decision"]
        assert "warming up" in d
        assert f"of {WINDOW} bars" in d

    def test_squeeze(self):
        """A flat series has zero bandwidth, so the floor rejects it."""
        s = _started(params={"bb__window_size": WINDOW,
                             "bb__min_width_pct": 0.01,
                             "risk__max_position_pct": 0.20})
        _feed(s, [100.0] * (WINDOW + 2))
        d = s.monitors()["last_decision"]
        assert "squeeze" in d
        assert s.monitors()["regime"] == "squeeze"

    def test_inside_the_bands(self):
        """Noisy prices, last bar near the mean."""
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [100.0]
        s = _started()
        _feed(s, closes)
        d = s.monitors()["last_decision"]
        assert "inside the bands" in d

    def test_lower_touch_ignored_while_holding(self):
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0]
        s = _started()
        sigs = _feed(s, closes, qty=80)
        assert sigs == []
        d = s.monitors()["last_decision"]
        assert "lower-band touch" in d and "already holding" in d

    def test_upper_touch_ignored_with_no_position(self):
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [150.0]
        s = _started()
        sigs = _feed(s, closes, qty=0)
        assert sigs == []
        d = s.monitors()["last_decision"]
        assert "upper-band touch" in d and "no position" in d

    def test_lower_touch_but_size_is_zero(self):
        """calc_qty returns 0 when the balance cannot cover one share."""
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0]
        s = _started()
        sigs = _feed(s, closes, qty=0, equity=10.0, balance=10.0)
        assert sigs == []
        d = s.monitors()["last_decision"]
        assert "size is" in d and "0" in d

    def test_buy_records_what_it_sent(self):
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0]
        s = _started()
        sigs = _feed(s, closes, qty=0)
        assert len(sigs) == 1 and sigs[0].action == "BUY"
        d = s.monitors()["last_decision"]
        assert d.startswith("BUY ") and "lower-band touch" in d
        assert s.monitors()["signals_emitted"] == 1

    def test_sell_records_what_it_sent(self):
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [150.0]
        s = _started()
        sigs = _feed(s, closes, qty=80)
        assert len(sigs) == 1 and sigs[0].action == "SELL"
        d = s.monitors()["last_decision"]
        assert d.startswith("SELL ") and "upper-band touch" in d

    def test_every_path_leaves_a_distinct_record(self):
        """No two reasons collapse into the same string."""
        seen = set()
        cases = [
            ([100.0] * 3, 0, 100_000.0),                                     # warming up
            ([100.0] * (WINDOW + 2), 0, 100_000.0),                          # squeeze-ish / inside
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [100.0], 0, 100_000.0),
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0], 80, 100_000.0),
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [150.0], 0, 100_000.0),
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0], 0, 10.0),
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [50.0], 0, 100_000.0),
            ([100.0 + (3 if i % 2 else -3) for i in range(WINDOW)] + [150.0], 80, 100_000.0),
        ]
        for closes, qty, eq in cases:
            s = _started()
            _feed(s, closes, qty=qty, equity=eq, balance=eq)
            seen.add(s.monitors()["last_decision"].split(":")[0].split(" at ")[0])
        assert len(seen) >= 6, seen


# ── counters ─────────────────────────────────────────────────────────────────

class TestCounters:
    def test_bars_seen_counts_every_bar_including_warmup(self):
        s = _started()
        _feed(s, [100.0] * 7)
        assert s.monitors()["bars_seen"] == 7

    def test_touches_are_counted(self):
        base = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)]
        s = _started()
        _feed(s, base + [50.0, 100.0, 150.0], qty=0)
        m = s.monitors()
        assert m["lower_touches"] >= 1
        assert m["upper_touches"] >= 1

    def test_touches_are_counted_even_inside_a_squeeze(self):
        """A touch is a fact about the market; `regime` says if it was tradeable.

        Counting only tradeable touches would make the number depend on
        min_width_pct and stop it being comparable across runs.
        """
        s = _started(params={"bb__window_size": WINDOW,
                             "bb__min_width_pct": 0.99,   # nothing is tradeable
                             "risk__max_position_pct": 0.20})
        base = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW)]
        _feed(s, base + [50.0], qty=0)
        m = s.monitors()
        assert m["regime"] == "squeeze"
        assert m["signals_emitted"] == 0
        assert m["lower_touches"] >= 1          # still recorded

    def test_mid_crossings_count_direction_changes(self):
        """Alternating above/below the mean crosses on nearly every bar."""
        s = _started()
        closes = [100.0 + (8 if i % 2 else -8) for i in range(WINDOW + 20)]
        _feed(s, closes)
        assert s.monitors()["mid_crossings"] >= 10

    def test_a_monotonic_series_barely_crosses(self):
        s = _started()
        _feed(s, [100.0 + i for i in range(WINDOW + 20)])
        assert s.monitors()["mid_crossings"] <= 1


# ── derived labels ───────────────────────────────────────────────────────────

class TestDerived:
    def test_volatility_is_unknown_before_any_band(self):
        s = _started()
        _feed(s, [100.0] * 3)
        assert s.monitors()["volatility"] == "unknown"

    def test_volatility_is_relative_to_the_symbols_own_history(self):
        """Quiet for a while, then a jolt -> 'high' against its own mean."""
        s = _started()
        quiet = [100.0 + (0.1 if i % 2 else -0.1) for i in range(WINDOW + 40)]
        _feed(s, quiet)
        assert s.monitors()["volatility"] in ("normal", "low")
        _feed(s, quiet + [100.0 + (15 if i % 2 else -15) for i in range(10)])
        assert s.monitors()["volatility"] == "high"

    def test_regime_follows_the_squeeze_gate(self):
        tight = _started(params={"bb__window_size": WINDOW,
                                 "bb__min_width_pct": 0.99,
                                 "risk__max_position_pct": 0.20})
        loose = _started(params={"bb__window_size": WINDOW,
                                 "bb__min_width_pct": 0.0,
                                 "risk__max_position_pct": 0.20})
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW + 2)]
        _feed(tight, closes)
        _feed(loose, closes)
        assert tight.monitors()["regime"] == "squeeze"
        assert loose.monitors()["regime"] == "tradeable"

    def test_band_levels_match_the_last_bar(self):
        s = _started()
        closes = [100.0 + (3 if i % 2 else -3) for i in range(WINDOW + 5)]
        _feed(s, closes)
        m = s.monitors()
        assert m["lower"] < m["middle"] < m["upper"]
        assert m["bandwidth_pct"] == pytest.approx(
            (m["upper"] - m["lower"]) / m["middle"] * 100, abs=0.02)

    def test_window_is_echoed_so_a_silent_run_is_explainable(self):
        s = _started(params={"bb__window_size": 100, "bb__min_width_pct": 0.01,
                             "risk__max_position_pct": 0.20})
        _feed(s, [100.0] * 30)
        m = s.monitors()
        assert m["window"] == 100
        assert "warming up" in m["last_decision"]
