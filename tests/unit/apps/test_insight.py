"""
tests/unit/apps/test_insight.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the `insight` command.

Weighted towards the two defects that running it on real data exposed, both of
which were silent -- the report rendered, it just said nothing true:

  * the epoch conversion read a naive Taipei stamp as machine-local time, so
    the market half of every report was skewed by the machine's own offset;
  * the regime thresholds were borrowed from a rolling window and applied to a
    whole session, where 98.3% of real days fall in one bucket and `trending`
    is unreachable.

Neither raised. A test that only checks "a report came out" would have passed
on both, so the measures are tested against known values and against the
property that was actually broken.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import time
from datetime import datetime
from datetime import timedelta

import pytest

from cjtrade.apps import insight
from cjtrade.apps.insight import Activity
from cjtrade.apps.insight import RANGING_BELOW
from cjtrade.apps.insight import TRENDING_ABOVE
from cjtrade.apps.insight import TripStats
from cjtrade.apps.insight import _epoch_to_taipei
from cjtrade.apps.insight import _open_price_db
from cjtrade.apps.insight import _regime_of
from cjtrade.apps.insight import _to_epoch
from cjtrade.apps.insight import build
from cjtrade.apps.insight import by_regime
from cjtrade.apps.insight import efficiency_ratio
from cjtrade.apps.insight import find_problems
from cjtrade.apps.insight import join_by_day
from cjtrade.apps.insight import load_sessions
from cjtrade.apps.insight import main
from cjtrade.apps.insight import render_markdown
from cjtrade.apps.insight import resolve
from cjtrade.apps.insight import summarise_activity
from cjtrade.apps.insight import summarise_trips
from cjtrade.apps.insight import trendiness
from cjtrade.pkgs.models.backtest import BacktestResult

# A bar that exists in this machine's price history, used as the fixed point
# for the conversion: epoch 1673830860 is 01:01 UTC, which is 09:01 in Taipei
# -- one minute after the Taiwan market opens, which is what a 1m bar at the
# start of a session should look like.
KNOWN_EPOCH = 1673830860
KNOWN_TAIPEI = datetime(2023, 1, 16, 9, 1)


# ══════════════════════════════════════════════════════════════════════════
#  Time
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def machine_timezone(request, monkeypatch):
    """Run a test as though the machine were somewhere else."""
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize("machine_timezone", [
    "UTC", "Asia/Taipei", "America/New_York", "Europe/London",
    "Pacific/Kiritimati",          # UTC+14, the far side of Taipei
], indirect=True)
def test_conversion_is_the_same_wherever_it_runs(machine_timezone):
    """The regression test for the original defect.

    `datetime.timestamp()` on a naive value reads it as the machine's local
    time, so the first version of this conversion moved every bar by the
    machine's own offset -- 16 hours on the laptop it was written on. A report
    about a Taiwan market should not change because the reader is in London.
    """
    assert _to_epoch(KNOWN_TAIPEI) == KNOWN_EPOCH
    assert _epoch_to_taipei(KNOWN_EPOCH) == KNOWN_TAIPEI


def test_epoch_round_trips():
    for ts in range(1_600_000_000, 1_700_000_000, 997_331):
        assert _to_epoch(_epoch_to_taipei(ts)) == ts


def test_taipei_is_eight_hours_ahead_of_utc():
    """Stated as the property rather than the arithmetic, so a change to
    TAIPEI_OFFSET that happens to keep the round trip consistent still fails."""
    assert _epoch_to_taipei(0) == datetime(1970, 1, 1, 8, 0)
    assert _to_epoch(datetime(1970, 1, 1, 8, 0)) == 0


# ══════════════════════════════════════════════════════════════════════════
#  Market measures
# ══════════════════════════════════════════════════════════════════════════

def test_efficiency_of_a_straight_line_is_total():
    assert efficiency_ratio([10, 11, 12, 13, 14]) == pytest.approx(100.0)


def test_efficiency_of_a_path_that_returns_is_nothing():
    assert efficiency_ratio([10, 11, 10, 11, 10]) == pytest.approx(0.0)


def test_efficiency_is_half_when_half_the_path_is_retraced():
    # Up 4, back 2: net 2 over a path of 6.
    assert efficiency_ratio([10, 14, 12]) == pytest.approx(100 * 2 / 6)


@pytest.mark.parametrize("closes", [[], [5.0], [0.0, 0.0, 0.0]])
def test_efficiency_degenerate_inputs_are_zero_not_an_error(closes):
    assert efficiency_ratio(closes) == 0.0


def test_efficiency_cannot_exceed_one_hundred():
    assert efficiency_ratio([1, 1000]) <= 100.0


def test_trendiness_does_not_depend_on_session_length():
    """The property the raw ratio lacks, and the reason the regime buckets
    were dead.

    A random walk is a random walk whether it is 60 bars or 600; the raw
    efficiency falls as 1/sqrt(n) while trendiness stays put. Without this,
    one threshold cannot serve both a session and a rolling window.
    """
    rng = random.Random(20260101)
    scores = {}
    for n in (60, 240, 600):
        runs = []
        for _ in range(60):
            price, closes = 100.0, []
            for _ in range(n):
                price += rng.choice((-0.1, 0.1))
                closes.append(price)
            runs.append(trendiness(closes))
        scores[n] = sum(runs) / len(runs)
    # Every length lands near chance, which is what 1.0 is defined to mean.
    for n, score in scores.items():
        assert 0.6 < score < 1.4, f"{n} bars scored {score:.2f}"
    # And they agree with each other, rather than drifting with length.
    assert max(scores.values()) - min(scores.values()) < 0.5


def test_trendiness_of_a_straight_line_grows_with_length():
    """A one-way move is more remarkable over 600 bars than over 60, because
    chance explains less of it. The raw ratio calls both of them 100."""
    short = trendiness([100 + i * 0.1 for i in range(60)])
    long = trendiness([100 + i * 0.1 for i in range(600)])
    assert efficiency_ratio([100 + i * 0.1 for i in range(60)]) == \
        pytest.approx(efficiency_ratio([100 + i * 0.1 for i in range(600)]))
    assert long > short > TRENDING_ABOVE


def test_trendiness_matches_the_random_walk_baseline_by_construction():
    closes = [100 + i * 0.1 for i in range(101)]
    assert trendiness(closes) == pytest.approx(
        efficiency_ratio(closes) / (100.0 / math.sqrt(100)))


@pytest.mark.parametrize("closes", [[], [1.0], [1.0, 2.0]])
def test_trendiness_degenerate_inputs_are_zero(closes):
    assert trendiness(closes) == 0.0


@pytest.mark.parametrize("value, expected", [
    (0.0, "ranging"),
    (RANGING_BELOW - 0.01, "ranging"),
    (RANGING_BELOW, "neutral"),
    (1.0, "neutral"),
    (TRENDING_ABOVE, "neutral"),
    (TRENDING_ABOVE + 0.01, "trending"),
    (9.0, "trending"),
])
def test_regime_boundaries(value, expected):
    assert _regime_of(value) == expected


def test_every_regime_is_reachable_by_a_realistic_session():
    """The guard against the bug this replaced.

    The previous thresholds (raw efficiency over 40 / under 20) put 3,918 of
    3,987 real sessions in one bucket and admitted one single trending day, so
    the regime table could not inform. Any future retuning has to keep all
    three buckets reachable at session length.
    """
    rng = random.Random(7)
    seen = set()
    for drift in (0.0, 0.004, 0.02, 0.08):
        price, closes = 100.0, []
        for _ in range(266):                      # a median real session
            price += drift + rng.choice((-0.1, 0.1))
            closes.append(price)
        seen.add(_regime_of(trendiness(closes)))
    assert seen == {"ranging", "neutral", "trending"}


# ══════════════════════════════════════════════════════════════════════════
#  The price database
# ══════════════════════════════════════════════════════════════════════════

def _price_db(path, symbol="2317", days=3, bars=20, start=KNOWN_TAIPEI):
    """A miniature of the real arenax_prices table."""
    con = sqlite3.connect(path)
    con.execute(
        "create table arenax_prices (symbol text, timeframe text, "
        "ts integer, open real, high real, low real, close real, "
        "volume real, source text, adjusted integer)")
    rows = []
    for day in range(days):
        opening = start + timedelta(days=day)
        for bar in range(bars):
            stamp = opening + timedelta(minutes=bar)
            close = 100.0 + day * 10 + bar          # one-way inside each day
            rows.append((symbol, "1m", _to_epoch(stamp), close - 0.5,
                         close + 1, close - 1, close, 1000.0, "test", 0))
    con.executemany("insert into arenax_prices values (?,?,?,?,?,?,?,?,?,?)",
                    rows)
    con.commit()
    con.close()
    return path


def test_load_sessions_groups_by_taipei_calendar_day(tmp_path):
    con = _open_price_db(_price_db(tmp_path / "p.db"))
    sessions = load_sessions(con, "2317", KNOWN_TAIPEI - timedelta(days=1),
                             KNOWN_TAIPEI + timedelta(days=5))
    assert [s.date for s in sessions] == ["2023-01-16", "2023-01-17",
                                          "2023-01-18"]
    assert [s.bars for s in sessions] == [20, 20, 20]
    first = sessions[0]
    assert first.open == pytest.approx(99.5)       # open of the first bar
    assert first.close == pytest.approx(119.0)     # close of the last
    assert first.high == pytest.approx(120.0)
    assert first.low == pytest.approx(99.0)        # low of the first bar
    assert first.regime == "trending"              # built as one-way
    con.close()


def test_load_sessions_honours_the_window(tmp_path):
    con = _open_price_db(_price_db(tmp_path / "p.db", days=5))
    sessions = load_sessions(con, "2317", KNOWN_TAIPEI + timedelta(days=1),
                             KNOWN_TAIPEI + timedelta(days=2, hours=12))
    assert [s.date for s in sessions] == ["2023-01-17", "2023-01-18"]
    con.close()


def test_load_sessions_ignores_other_symbols_and_timeframes(tmp_path):
    path = _price_db(tmp_path / "p.db")
    con = sqlite3.connect(path)
    con.execute("insert into arenax_prices values "
                "('9999','1m',?,1,1,1,1,1,'test',0)", (_to_epoch(KNOWN_TAIPEI),))
    con.execute("insert into arenax_prices values "
                "('2317','1d',?,1,1,1,1,1,'test',0)", (_to_epoch(KNOWN_TAIPEI),))
    con.commit()
    con.close()
    con = _open_price_db(path)
    sessions = load_sessions(con, "2317", KNOWN_TAIPEI - timedelta(days=1),
                             KNOWN_TAIPEI + timedelta(days=5))
    assert sum(s.bars for s in sessions) == 60       # the 1d row excluded
    con.close()


def test_open_price_db_returns_none_for_a_missing_file(tmp_path):
    assert _open_price_db(tmp_path / "nope.db") is None


def test_open_price_db_returns_none_for_a_file_without_the_table(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert _open_price_db(path) is None


def test_open_price_db_does_not_write_to_the_database(tmp_path):
    """Opened read-only on purpose: a report must never be able to damage the
    price history it is reading, least of all while a broker is using it."""
    con = _open_price_db(_price_db(tmp_path / "p.db"))
    with pytest.raises(sqlite3.OperationalError):
        con.execute("delete from arenax_prices")
    con.close()


# ══════════════════════════════════════════════════════════════════════════
#  The strategy side
# ══════════════════════════════════════════════════════════════════════════

def _fill(time, action, price, qty=1000, symbol="2317", **extra):
    row = {"time": time, "symbol": symbol, "action": action,
           "quantity": qty, "price": price, "commission": 0.0,
           "tax": 0.0, "slippage_cost": 0.0}
    row.update(extra)
    return row


def test_summarise_activity_counts_both_sides():
    act = summarise_activity([
        _fill("2025-10-13T09:17:00", "BUY", 100.0),
        _fill("2025-10-13T10:17:00", "SELL", 101.0),
        _fill("2025-10-14T09:17:00", "BUY", 102.0, symbol="2330"),
    ])
    assert (act.fills, act.buys, act.sells) == (3, 2, 1)
    assert act.symbols == ["2317", "2330"]
    assert act.traded_value == pytest.approx(303_000.0)
    assert act.first_fill == "2025-10-13T09:17:00"
    assert act.last_fill == "2025-10-14T09:17:00"


def test_summarise_activity_of_nothing_is_empty_not_an_error():
    act = summarise_activity([])
    assert act.fills == 0 and act.symbols == [] and act.costs == 0.0
    assert act.first_fill is None


def test_costs_are_the_three_components_added_up():
    act = summarise_activity([
        _fill("2025-10-13T09:17:00", "BUY", 100.0,
              commission=142.5, tax=0.0, slippage_cost=12.0),
        _fill("2025-10-13T10:17:00", "SELL", 101.0,
              commission=143.9, tax=303.0, slippage_cost=8.0),
    ])
    assert act.commission == pytest.approx(286.4)
    assert act.tax == pytest.approx(303.0)
    assert act.slippage == pytest.approx(20.0)
    assert act.costs == pytest.approx(609.4)


def test_fee_floor_is_counted_only_when_the_minimum_actually_bound():
    """An order big enough to owe more than NT$20 that happens to be charged
    NT$20 is not a small order -- it is a backend quirk -- so the test pins
    both halves of the condition."""
    act = summarise_activity([
        # 1,000 at 1.0 owes 1.43, pays the 20 floor: genuinely too small.
        _fill("2025-10-13T09:17:00", "BUY", 1.0, qty=1000, commission=20.0),
        # 1,000 at 100 owes 142.50; a 20 charge here is not the floor binding.
        _fill("2025-10-13T09:18:00", "BUY", 100.0, qty=1000, commission=20.0),
        _fill("2025-10-13T09:19:00", "BUY", 100.0, qty=1000, commission=142.5),
    ])
    assert act.fee_floor_fills == 1


def test_summarise_trips_describes_wins_and_losses():
    result = BacktestResult(
        initial_balance=100_000.0, final_balance=100_500.0,
        equity_curve=[], fill_history=[
            _fill("2025-10-13T09:00:00", "BUY", 100.0),
            _fill("2025-10-13T10:00:00", "SELL", 101.0),    # +1000
            _fill("2025-10-14T09:00:00", "BUY", 100.0),
            _fill("2025-10-16T10:00:00", "SELL", 99.5),     # -500, 2 days
        ])
    trips = summarise_trips(result.compute_round_trips())
    assert trips.count == 2 and trips.wins == 1 and trips.losses == 1
    assert trips.win_rate == 50.0
    assert trips.gross_pnl == pytest.approx(500.0)
    assert trips.profit_factor == pytest.approx(2.0)
    assert trips.best == pytest.approx(1000.0)
    assert trips.worst == pytest.approx(-500.0)
    assert trips.hold_buckets == {"same day": 1, "1-2 days": 1}


def test_profit_factor_is_undefined_rather_than_infinite_with_no_losses():
    """A ratio with no denominator is not a big number. Reporting `inf` or a
    made-up ceiling would read as an extraordinary strategy."""
    result = BacktestResult(
        initial_balance=1.0, final_balance=1.0, equity_curve=[],
        fill_history=[_fill("2025-10-13T09:00:00", "BUY", 100.0),
                      _fill("2025-10-13T10:00:00", "SELL", 101.0)])
    assert summarise_trips(result.compute_round_trips()).profit_factor is None


def test_longest_losing_streak_counts_consecutive_losses():
    trips = summarise_trips([
        type("T", (), {"pnl": p, "holding_days": 0,
                       "exit_time": "2025-10-13T10:00:00"})()
        for p in (-1, -1, -1, 5, -1, -1, 9)])
    assert trips.longest_losing_streak == 3


def test_summarise_trips_of_nothing_is_empty():
    assert summarise_trips([]).count == 0


# ══════════════════════════════════════════════════════════════════════════
#  The join
# ══════════════════════════════════════════════════════════════════════════

def _sessions(regimes):
    return [insight.SessionStats(
        date=date, bars=266, open=100.0, high=101.0, low=99.0, close=100.0,
        change_pct=0.0, range_pct=2.0, vol_bp=13.0, efficiency=5.0,
        trendiness=trend, regime=_regime_of(trend))
        for date, trend in regimes]


def test_join_keeps_the_days_the_strategy_sat_out():
    """The silent days are the evidence for "why did it stop", so a join that
    dropped them would delete the answer to the question the report exists
    to ask."""
    sessions = _sessions([("2025-10-13", 2.0), ("2025-10-14", 0.5),
                          ("2025-10-15", 0.5)])
    days = join_by_day(sessions, [_fill("2025-10-13T09:17:00", "BUY", 100.0)], [])
    assert [d.date for d in days] == ["2025-10-13", "2025-10-14", "2025-10-15"]
    assert [d.fills for d in days] == [1, 0, 0]


def test_join_attributes_pnl_to_the_day_the_trip_closed():
    trip = type("T", (), {"pnl": 250.0, "holding_days": 2,
                          "exit_time": "2025-10-15T11:00:00"})()
    days = join_by_day(_sessions([("2025-10-13", 2.0), ("2025-10-15", 0.5)]),
                       [], [trip])
    assert [(d.date, d.pnl, d.trips_closed) for d in days] == [
        ("2025-10-13", 0.0, 0), ("2025-10-15", 250.0, 1)]


def test_by_regime_separates_where_the_money_came_from():
    """The bucket that answers "this stock only suits the strategy sometimes"."""
    sessions = _sessions([("2025-10-13", 2.0), ("2025-10-14", 2.0),
                          ("2025-10-15", 0.2), ("2025-10-16", 0.2)])
    trips = [type("T", (), {"pnl": pnl, "holding_days": 0,
                            "exit_time": f"2025-10-1{day}T11:00:00"})()
             for day, pnl in ((3, 500.0), (4, 300.0), (5, -900.0))]
    buckets = by_regime(join_by_day(sessions, [], trips))
    assert buckets["trending"]["pnl"] == pytest.approx(800.0)
    assert buckets["trending"]["winning_days"] == 2
    assert buckets["ranging"]["pnl"] == pytest.approx(-900.0)
    assert buckets["ranging"]["losing_days"] == 1
    assert buckets["ranging"]["sessions"] == 2


def test_by_regime_omits_regimes_with_no_sessions():
    buckets = by_regime(join_by_day(_sessions([("2025-10-13", 0.2)]), [], []))
    assert list(buckets) == ["ranging"]


# ══════════════════════════════════════════════════════════════════════════
#  Findings
# ══════════════════════════════════════════════════════════════════════════

def _findings(act, trips, days=(), net=0.0, window=None, trading_days=0):
    window = window or (datetime(2025, 10, 13), datetime(2025, 10, 31))
    return {f.what: f for f in find_problems(
        act, trips, list(days), net, window, trading_days)}


def test_a_flat_gross_beside_a_large_loss_is_reported_as_a_cost_problem():
    """The regression test for the second defect found by running it.

    The real run was 349 round trips for -899 gross against 24,125 of costs:
    net -25,024, which is almost entirely fees. The first version only looked
    at costs when gross was POSITIVE, so on the one run where costs were the
    whole story the report said nothing about them.
    """
    act = Activity(fills=482, buys=241, sells=241, traded_value=8_248_235.0,
                   commission=11_753.74, tax=12_371.0,
                   median_order_value=17_076.0)
    trips = TripStats(count=349, gross_pnl=-899.0, median_hold_days=0.0,
                      hold_buckets={"same day": 309})
    found = _findings(act, trips, net=-25_023.74)
    assert "The loss is the cost of trading, not the trading" in found
    finding = found["The loss is the cost of trading, not the trading"]
    assert finding.severity == "high"
    assert "24,125" in finding.evidence and "96%" in finding.evidence


def test_costs_against_a_positive_gross_are_reported_as_a_share_of_it():
    act = Activity(fills=50, commission=400.0, tax=200.0,
                   median_order_value=20_000.0)
    trips = TripStats(count=25, gross_pnl=1_000.0)
    found = _findings(act, trips, net=400.0)
    assert "Costs eat most of the gross profit" in found
    assert "60%" in found["Costs eat most of the gross profit"].evidence


def test_modest_costs_against_a_healthy_gross_are_not_flagged():
    act = Activity(fills=50, commission=50.0, tax=25.0,
                   median_order_value=20_000.0)
    trips = TripStats(count=25, gross_pnl=10_000.0)
    assert "Costs eat most of the gross profit" not in _findings(
        act, trips, net=9_925.0)


def test_a_run_with_no_fills_says_so_and_stops():
    found = _findings(Activity(), TripStats(), trading_days=131)
    assert list(found) == ["The strategy never traded"]
    assert "131 trading day(s)" in found["The strategy never traded"].evidence


def test_the_no_fills_finding_counts_days_off_the_equity_curve():
    """`days` comes from the market join, which is keyed on the symbols that
    were filled -- so for a run with no fills it is always empty and would
    report "0 trading day(s)", which reads as a broken report."""
    found = _findings(Activity(), TripStats(), days=[], trading_days=42)
    assert "42 trading day(s)" in found["The strategy never traded"].evidence


def test_fills_with_no_round_trips_is_flagged_as_a_missing_exit():
    found = _findings(Activity(fills=3, median_order_value=10_000.0),
                      TripStats(count=0), net=-100.0)
    assert "It opened positions and never closed any" in found


def test_churn_is_flagged_once_there_are_enough_trips_to_mean_it():
    act = Activity(fills=700, median_order_value=10_000.0)
    churn = "Positions are held for minutes, not days"
    assert churn in _findings(act, TripStats(
        count=349, median_hold_days=0.0, hold_buckets={"same day": 309}))
    # Three same-day trips is not a finding about the strategy's holding time.
    assert churn not in _findings(act, TripStats(
        count=3, median_hold_days=0.0, hold_buckets={"same day": 3}))


def test_an_early_stop_is_flagged_with_the_share_of_the_window_left_idle():
    act = Activity(fills=482, median_order_value=10_000.0,
                   last_fill="2025-11-07T11:00:00")
    found = _findings(act, TripStats(count=349, gross_pnl=5_000.0),
                      net=5_000.0,
                      window=(datetime(2025, 10, 13), datetime(2026, 4, 30)))
    stop = "It stopped trading long before the run ended"
    assert stop in found and "87%" in found[stop].evidence


def test_trading_to_the_end_of_the_window_is_not_flagged_as_an_early_stop():
    act = Activity(fills=482, median_order_value=10_000.0,
                   last_fill="2025-10-30T11:00:00")
    assert "It stopped trading long before the run ended" not in _findings(
        act, TripStats(count=349, gross_pnl=5_000.0), net=5_000.0,
        window=(datetime(2025, 10, 13), datetime(2025, 10, 31)))


def test_winning_often_and_losing_money_is_called_out():
    found = _findings(Activity(fills=100, median_order_value=10_000.0),
                      TripStats(count=50, win_rate=70.0, gross_pnl=5_000.0),
                      net=-2_000.0)
    assert "It wins more often than it loses and still loses money" in found


def test_a_single_profitable_regime_is_named():
    sessions = _sessions([("2025-10-13", 2.0), ("2025-10-15", 0.2)])
    trips = [type("T", (), {"pnl": pnl, "holding_days": 0,
                            "exit_time": f"2025-10-1{day}T11:00:00"})()
             for day, pnl in ((3, 900.0), (5, -400.0))]
    days = join_by_day(sessions, [_fill("2025-10-13T09:00:00", "BUY", 100.0)],
                       trips)
    found = _findings(Activity(fills=1, median_order_value=10_000.0),
                      TripStats(count=2, gross_pnl=500.0), days, net=500.0)
    assert "It only makes money when the market is trending" in found


def test_a_clean_run_says_nothing_was_flagged_rather_than_staying_silent():
    """An empty findings section would read as an endorsement."""
    found = _findings(Activity(fills=40, median_order_value=50_000.0,
                               commission=200.0, last_fill="2025-10-30T11:00:00"),
                      TripStats(count=20, win_rate=55.0, gross_pnl=20_000.0,
                                median_hold_days=4.0),
                      net=19_800.0)
    assert list(found) == ["Nothing flagged"]
    assert found["Nothing flagged"].severity == "low"


def test_every_finding_carries_its_evidence_and_its_reading():
    """The three fields are kept apart so a reader can take the number and
    reject the interpretation."""
    act = Activity(fills=482, commission=11_753.0, tax=12_371.0,
                   median_order_value=17_076.0, last_fill="2025-11-07T11:00:00")
    trips = TripStats(count=349, gross_pnl=-899.0, median_hold_days=0.0,
                      hold_buckets={"same day": 309})
    findings = find_problems(act, trips, [], -25_023.0,
                             (datetime(2025, 10, 13), datetime(2026, 4, 30)))
    assert findings
    for f in findings:
        assert f.severity in ("high", "medium", "low")
        assert f.what and f.evidence and f.why
        assert any(ch.isdigit() for ch in f.evidence), f.what


# ══════════════════════════════════════════════════════════════════════════
#  Assembly and rendering
# ══════════════════════════════════════════════════════════════════════════

def _result(**over):
    curve = [{"time": f"2023-01-16T09:{m:02d}:00", "value": 100_000.0 + m}
             for m in range(1, 20)]
    fills = [_fill("2023-01-16T09:05:00", "BUY", 100.0),
             _fill("2023-01-16T09:15:00", "SELL", 101.0, commission=143.9,
                   tax=303.0)]
    kwargs = dict(initial_balance=100_000.0, final_balance=100_553.1,
                  equity_curve=curve, fill_history=fills,
                  session_id="deadbeefcafe0000", start_time="2023-01-16T09:00:00",
                  final_equity=100_553.1)
    kwargs.update(over)
    return BacktestResult(**kwargs)


@pytest.fixture
def priced(tmp_path, monkeypatch):
    """A machine whose price history covers the fixture run's window."""
    path = _price_db(tmp_path / "arenax_price.db", symbol="2317", days=1,
                     bars=19)
    monkeypatch.setattr(insight.paths, "price_db_path", lambda: path)
    return path


def test_build_joins_the_pickle_to_the_price_history(priced, tmp_path):
    doc = build(_result(), tmp_path / "engine_deadbeef.pkl")
    assert doc["market"]["available"] is True
    assert "2317" in doc["market"]["symbols"]
    assert doc["market"]["symbols"]["2317"]["bars"] == 19
    assert doc["by_day"] and doc["by_day"][0]["fills"] == 2
    assert doc["run"]["session_id"] == "deadbeefcafe0000"
    assert doc["activity"]["fills"] == 2
    assert doc["round_trips"]["count"] == 1


def test_build_reports_the_absence_of_a_price_database_instead_of_guessing(
        tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_result(), tmp_path / "engine_x.pkl")
    assert doc["market"]["available"] is False
    assert doc["market"]["symbols"] == {}
    assert doc["by_day"] == [] and doc["by_regime"] == {}
    # The strategy half is unaffected: half a report beats none.
    assert doc["activity"]["fills"] == 2


def test_build_splits_realised_from_unrealised(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_result(final_balance=90_000.0, final_equity=105_000.0),
                tmp_path / "engine_x.pkl")
    assert doc["run"]["realised_pnl"] == pytest.approx(-10_000.0)
    assert doc["run"]["unrealised_pnl"] == pytest.approx(15_000.0)
    assert doc["run"]["net_pnl"] == pytest.approx(5_000.0)


def test_build_falls_back_to_final_balance_when_equity_was_not_recorded(
        tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_result(final_equity=None), tmp_path / "engine_x.pkl")
    assert doc["run"]["final_equity"] == pytest.approx(100_553.1)


def test_build_survives_an_empty_run(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_result(equity_curve=[], fill_history=[], final_equity=None),
                tmp_path / "engine_x.pkl")
    assert doc["findings"][0]["what"] == "The strategy never traded"
    assert render_markdown(doc).startswith("# Run insight")


def test_the_document_is_json_serialisable(priced, tmp_path):
    doc = build(_result(), tmp_path / "engine_x.pkl")
    assert json.loads(json.dumps(doc, default=str))["run"]["session_id"]


def test_markdown_leads_with_the_findings(priced, tmp_path):
    md = render_markdown(build(_result(), tmp_path / "engine_x.pkl"))
    assert md.index("## What stands out") < md.index("## The run")


def test_markdown_always_states_its_blind_spots_and_caveats(priced, tmp_path):
    """Both sections are the point of the report: a reader who does not know
    the gate refusals are missing will blame the strategy for the engine."""
    md = render_markdown(build(_result(), tmp_path / "engine_x.pkl"))
    assert "## What this cannot see" in md
    assert "## How these numbers lie" in md
    assert "Risk-gate refusals" in md


def test_markdown_explains_what_the_trend_number_means(priced, tmp_path):
    md = render_markdown(build(_result(), tmp_path / "engine_x.pkl"))
    assert "random walk" in md


# ══════════════════════════════════════════════════════════════════════════
#  Finding the run
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def reports(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    directory.mkdir()
    monkeypatch.setattr(insight.paths, "reports_dir", lambda: directory)
    for index, name in enumerate(("engine_aaaa1111", "engine_bbbb2222",
                                  "engine_bbbb3333")):
        path = directory / f"{name}.pkl"
        _result(session_id=name[7:]).save(str(path))
        import os
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    return directory


def test_resolve_defaults_to_the_newest_run(reports):
    assert resolve(None).stem == "engine_bbbb3333"


def test_resolve_accepts_a_session_prefix(reports):
    assert resolve("aaaa").stem == "engine_aaaa1111"


def test_resolve_accepts_an_explicit_path(reports, tmp_path):
    path = reports / "engine_aaaa1111.pkl"
    assert resolve(str(path)) == path


def test_resolve_refuses_an_ambiguous_prefix_rather_than_picking_one(reports):
    with pytest.raises(SystemExit, match="matches 2 runs"):
        resolve("bbbb")


def test_resolve_does_not_match_every_run_through_the_file_name_prefix(reports):
    """Every file is engine_<id>, so matching the whole stem made a target of
    "e" match all of them -- an ambiguity error instead of a lookup."""
    with pytest.raises(SystemExit, match="no run matching"):
        resolve("engine")


def test_resolve_says_how_to_list_the_runs_when_nothing_matches(reports):
    with pytest.raises(SystemExit, match="insight --list"):
        resolve("zzzz")


def test_resolve_explains_an_empty_reports_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "reports_dir", lambda: tmp_path / "none")
    with pytest.raises(SystemExit, match="no runs found"):
        resolve(None)


# ══════════════════════════════════════════════════════════════════════════
#  The command
# ══════════════════════════════════════════════════════════════════════════

def test_main_writes_both_formats_and_prints_both_paths(reports, tmp_path,
                                                        capsys, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    out = tmp_path / "out"
    assert main(["aaaa", "--out", str(out)]) == 0

    md = out / "engine_aaaa1111.insight.md"
    js = out / "engine_aaaa1111.insight.json"
    assert md.is_file() and js.is_file()
    assert md.read_text(encoding="utf-8").startswith("# Run insight")
    assert json.loads(js.read_text(encoding="utf-8"))["findings"]

    printed = capsys.readouterr().out
    assert str(md) in printed and str(js) in printed


def test_main_prints_the_paths_last_so_they_are_not_scrolled_away(
        reports, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    main(["aaaa", "--out", str(tmp_path / "out"), "--stdout"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[-2].strip().startswith("report")
    assert lines[-1].strip().startswith("json")


def test_main_defaults_to_writing_beside_the_run(reports, tmp_path, capsys,
                                                 monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    main(["aaaa"])
    assert (reports / "engine_aaaa1111.insight.md").is_file()
    assert str(reports) in capsys.readouterr().out


def test_main_warns_when_the_market_half_is_empty(reports, tmp_path, capsys,
                                                  monkeypatch):
    """Stated on screen rather than left as empty sections, so a reader does
    not take a missing database for a quiet market."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    main(["aaaa", "--out", str(tmp_path / "out")])
    assert "no price database" in capsys.readouterr().out


def test_main_stdout_also_prints_the_report(reports, tmp_path, capsys,
                                            monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    main(["aaaa", "--out", str(tmp_path / "out"), "--stdout"])
    assert "## What stands out" in capsys.readouterr().out


def test_main_list_names_the_runs_and_the_directory(reports, capsys):
    assert main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert "aaaa1111" in printed and "bbbb3333" in printed
    assert str(reports) in printed


def test_main_list_is_not_an_error_when_there_is_nothing_to_list(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(insight.paths, "reports_dir", lambda: tmp_path / "none")
    assert main(["--list"]) == 0
    assert "No runs" in capsys.readouterr().out


def test_main_reports_an_unreadable_result_file_rather_than_a_traceback(
        tmp_path, monkeypatch):
    broken = tmp_path / "engine_broken.pkl"
    broken.write_text("not a pickle", encoding="utf-8")
    monkeypatch.setattr(insight.paths, "reports_dir", lambda: tmp_path)
    with pytest.raises(SystemExit, match="could not read"):
        main([str(broken)])


# ══════════════════════════════════════════════════════════════════════════
#  Provenance — which execution path produced the numbers
# ══════════════════════════════════════════════════════════════════════════
#
# The two paths that write a BacktestResult disagree, measured: on the same
# 32,229 bars of 2357 with the same Bollinger parameters, same-bar unconditional
# fills give 113 fills and -2,774, while limit orders that must wait for a close
# to cross give 101 and -3,016. So a report that does not say which path it came
# from is not interpretable, and the field has to survive a save/load cycle.

ONESHOT_PROVENANCE = {
    "path": "oneshot",
    "strategy": "BB",
    "interval": "1m",
    "symbols": ["2317"],
    "requested_start": "2023-01-16",
    "requested_end": "2023-01-20",
    "duration_days": 4,
    "start_was_explicit": True,
    "bars": 19,
    "params": {"bb__window_size": 100, "bb__std_dev": 2.0},
    "params_hash": "abc12345",
    "cost_model": {"commission_rate": 0.001425, "commission_discount": 1.0,
                   "min_commission": 20.0, "stock_tax_rate": 0.003,
                   "etf_tax_rate": 0.001, "slippage_model": "none",
                   "slippage_pct": 0.0005},
    "execution_model": "A signal fills in the bar that produced it.",
    "comparable_to_engine": False,
}


def test_provenance_survives_a_save_and_load(tmp_path):
    path = tmp_path / "oneshot_2317_abc12345.pkl"
    result = _result()
    result.provenance = dict(ONESHOT_PROVENANCE)
    result.save(str(path))
    assert BacktestResult.load(str(path)).provenance == ONESHOT_PROVENANCE


def test_a_result_pickled_before_provenance_existed_still_loads(tmp_path):
    """The field defaults to None, so an older run reports "unknown" rather
    than failing to open."""
    path = tmp_path / "engine_old.pkl"
    _result().save(str(path))
    assert BacktestResult.load(str(path)).provenance is None


def test_build_carries_provenance_through(priced, tmp_path):
    result = _result()
    result.provenance = dict(ONESHOT_PROVENANCE)
    doc = build(result, tmp_path / "oneshot_x.pkl")
    assert doc["provenance"]["path"] == "oneshot"
    assert doc["provenance"]["interval"] == "1m"


def test_markdown_states_the_execution_path_before_the_numbers(priced, tmp_path):
    """Placed ahead of the run summary on purpose: it governs how every number
    below it should be read."""
    result = _result()
    result.provenance = dict(ONESHOT_PROVENANCE)
    md = render_markdown(build(result, tmp_path / "oneshot_x.pkl"))
    assert "## How this run was produced" in md
    assert md.index("## How this run was produced") < md.index("## The run")
    assert "oneshot" in md


def test_markdown_warns_that_a_oneshot_is_not_engine_comparable(priced, tmp_path):
    result = _result()
    result.provenance = dict(ONESHOT_PROVENANCE)
    md = render_markdown(build(result, tmp_path / "oneshot_x.pkl"))
    assert "not** comparable" in md or "not comparable" in md


def test_markdown_says_so_when_provenance_is_missing(priced, tmp_path):
    """Silence would read as "this is fine"; an unknown path is a real caveat
    because the two paths produce different numbers."""
    md = render_markdown(build(_result(), tmp_path / "engine_x.pkl"))
    assert "records no provenance" in md


def test_markdown_lists_the_parameters_when_provenance_has_them(priced, tmp_path):
    result = _result()
    result.provenance = dict(ONESHOT_PROVENANCE)
    md = render_markdown(build(result, tmp_path / "oneshot_x.pkl"))
    assert "bb__window_size" in md and "bb__std_dev" in md


def test_a_random_start_date_is_flagged(priced, tmp_path):
    """An unseeded random window makes two "identical" runs incomparable, so
    it has to be visible in the report rather than only in the CLI."""
    result = _result()
    result.provenance = {**ONESHOT_PROVENANCE, "start_was_explicit": False}
    md = render_markdown(build(result, tmp_path / "oneshot_x.pkl"))
    assert "RANDOM" in md


# ══════════════════════════════════════════════════════════════════════════
#  Blind spots that provenance has closed must drop off the list
# ══════════════════════════════════════════════════════════════════════════

def test_parameters_leave_the_blind_spot_list_once_recorded():
    """A report that prints the parameters in one section and calls them
    invisible in another teaches the reader to distrust the section."""
    titles = [t for t, _ in insight.cannot_see(ONESHOT_PROVENANCE)]
    assert not any("parameters" in t.lower() for t in titles)
    assert not any("symbols" in t.lower() for t in titles)


def test_the_blind_spots_provenance_cannot_answer_remain():
    titles = [t for t, _ in insight.cannot_see(ONESHOT_PROVENANCE)]
    assert any("Risk-gate" in t for t in titles)
    assert any("bar by bar" in t for t in titles)


def test_without_provenance_every_blind_spot_is_listed():
    assert len(insight.cannot_see(None)) == len(insight.CANNOT_SEE)


def test_blind_spot_entries_are_pairs_whatever_the_tagging():
    for entry in insight.cannot_see(ONESHOT_PROVENANCE) + insight.cannot_see(None):
        assert len(entry) == 2, entry


# ══════════════════════════════════════════════════════════════════════════
#  Discovery across both kinds of run
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mixed_reports(tmp_path, monkeypatch):
    """One run from each path, as they are actually named on disk."""
    directory = tmp_path / "reports"
    directory.mkdir()
    monkeypatch.setattr(insight.paths, "reports_dir", lambda: directory)
    import os
    names = ("engine_aaaa1111", "oneshot_2357_bbbb2222")
    for index, name in enumerate(names):
        path = directory / f"{name}.pkl"
        _result(session_id=name.split("_")[-1]).save(str(path))
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    return directory


def test_available_runs_finds_both_paths(mixed_reports):
    stems = {p.stem for p in insight.available_runs()}
    assert stems == {"engine_aaaa1111", "oneshot_2357_bbbb2222"}


def test_resolve_finds_a_oneshot_by_session_prefix(mixed_reports):
    assert resolve("bbbb").stem == "oneshot_2357_bbbb2222"


def test_resolve_finds_a_oneshot_by_its_symbol(mixed_reports):
    """The symbol is in the file name, so it is a usable handle too."""
    assert resolve("2357").stem == "oneshot_2357_bbbb2222"


def test_neither_prefix_matches_every_run(mixed_reports):
    """"engine" and "oneshot" are file-name noise, not session ids."""
    for noise in ("engine", "oneshot"):
        with pytest.raises(SystemExit, match="no run matching"):
            resolve(noise)


def test_insight_output_is_not_picked_up_as_a_run(mixed_reports):
    """The reports it writes live beside the runs it read."""
    (mixed_reports / "engine_aaaa1111.insight.pkl").write_bytes(b"x")
    assert all(not p.name.endswith(".insight.pkl")
               for p in insight.available_runs())


def test_list_names_the_path_of_each_run(mixed_reports, capsys):
    assert main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert "oneshot" in printed and "engine" in printed


def test_the_terminal_summary_names_the_path_and_interval(
        mixed_reports, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    path = mixed_reports / "oneshot_2357_bbbb2222.pkl"
    result = BacktestResult.load(str(path))
    result.provenance = dict(ONESHOT_PROVENANCE)
    result.save(str(path))
    main(["bbbb", "--out", str(tmp_path / "out")])
    printed = capsys.readouterr().out
    assert "[oneshot, 1m]" in printed


def test_the_terminal_summary_warns_when_provenance_is_absent(
        mixed_reports, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    main(["aaaa", "--out", str(tmp_path / "out")])
    assert "no provenance" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════
#  Risk-adjusted performance
# ══════════════════════════════════════════════════════════════════════════
#
# These come from the same quantstats the HTML tearsheet uses. They are in the
# report so that comparing two runs does not require opening a browser or
# importing the library -- the omission was what sent a reviewer looking for
# quantstats.py in the first place.

def _curve(values, start="2025-01-02", daily=True):
    """An equity curve, one point per day or per minute."""
    out = []
    base = datetime.fromisoformat(f"{start}T09:01:00")
    for i, value in enumerate(values):
        stamp = base + (timedelta(days=i) if daily else timedelta(minutes=i))
        out.append({"time": stamp.isoformat(), "value": float(value)})
    return out


def _walk(n=140, seed=3, drift=-2.0):
    rng = random.Random(seed)
    value, out = 100_000.0, []
    for _ in range(n):
        value += drift + rng.uniform(-60, 60)
        out.append(value)
    return out


def _with_curve(curve):
    return BacktestResult(initial_balance=100_000.0, final_balance=curve[-1]["value"],
                          equity_curve=curve, fill_history=[], session_id="perf",
                          final_equity=curve[-1]["value"])


def test_performance_reports_the_metrics_a_tearsheet_would():
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert perf["available"] is True
    for key in ("sharpe", "sortino", "calmar", "cagr", "volatility_annual",
                "max_drawdown", "best_period", "worst_period",
                "winning_periods_pct", "value_at_risk_95", "cvar_95",
                "skew", "kurtosis", "recovery_factor", "ulcer_index"):
        assert key in perf, key


def test_performance_states_its_resolution_and_annualisation():
    """Every annualised number depends on these two, and to_returns() switches
    resolution silently depending on how long the run was."""
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert perf["resolution"] == "daily"
    assert perf["periods_per_year"] == 252
    assert perf["observations"] == 139


def test_a_single_day_run_is_marked_as_minute_resolution():
    """to_returns() falls back to minute returns for an intraday run and
    annualises at 252x270, which is not comparable with a daily figure."""
    perf = insight.performance(_with_curve(_curve(_walk(60), daily=False)))
    assert perf["resolution"] == "minute"
    assert perf["periods_per_year"] == 252 * 270


def test_the_minute_resolution_caveat_is_rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk(60), daily=False)),
                               tmp_path / "x.pkl"))
    assert "too short to resample" in md


@pytest.mark.parametrize("curve", [[], [100_000.0], [100_000.0, 100_500.0]])
def test_performance_declines_rather_than_inventing_a_number(curve):
    """One return observation has no dispersion. Saying so beats printing a
    Sharpe computed from it."""
    perf = insight.performance(_with_curve(_curve(curve)) if curve
                               else _result(equity_curve=[]))
    assert perf["available"] is False
    assert perf["reason"]


def test_an_undefined_ratio_is_null_not_infinity():
    """Calmar is CAGR / max drawdown, and a run that never drew down divides
    by zero. quantstats returns inf; `json.dumps(inf)` writes the bare token
    `Infinity`, which is not valid JSON and breaks a strict parser -- and the
    JSON document exists precisely to be parsed by something else."""
    rising = _curve([100_000.0 + i * 10 for i in range(40)])
    perf = insight.performance(_with_curve(rising))
    assert perf["max_drawdown"] == 0.0
    assert perf["calmar"] is None


def test_no_metric_is_ever_a_non_finite_float():
    for curve in (_curve([100_000.0 + i * 10 for i in range(40)]),
                  _curve(_walk()),
                  _curve([100_000.0] * 40)):
        perf = insight.performance(_with_curve(curve))
        for key, value in perf.items():
            if isinstance(value, float):
                assert math.isfinite(value), f"{key} = {value}"


def test_the_document_survives_a_strict_json_parser(tmp_path, monkeypatch):
    """`Infinity` and `NaN` are Python conveniences, not JSON. An agent
    parsing this in another language would reject them."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    rising = _curve([100_000.0 + i * 10 for i in range(40)])
    text = json.dumps(build(_with_curve(rising), tmp_path / "x.pkl"), default=str)
    for token in ("Infinity", "-Infinity", "NaN"):
        assert token not in text

    def reject(constant):
        raise AssertionError(f"illegal JSON constant {constant}")
    json.loads(text, parse_constant=reject)


def test_performance_survives_a_completely_flat_curve():
    perf = insight.performance(_with_curve(_curve([100_000.0] * 40)))
    assert perf["available"] is True
    assert perf["flat_periods"] == 39


def test_flat_periods_counts_days_the_equity_did_not_move():
    values = [100_000.0, 100_000.0, 100_500.0, 100_500.0, 101_000.0]
    perf = insight.performance(_with_curve(_curve(values)))
    assert perf["flat_periods"] == 2


def test_markdown_renders_the_metrics_table(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk())), tmp_path / "x.pkl"))
    assert "## Risk-adjusted performance" in md
    for label in ("Sharpe", "Sortino", "Calmar", "CAGR", "max drawdown",
                  "CVaR 95%", "skew", "kurtosis"):
        assert label in md, label


def test_markdown_pluralises_the_period_unit_correctly(tmp_path, monkeypatch):
    """"daily" reads as an adverb in prose and a noun in a table header."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk())), tmp_path / "x.pkl"))
    assert "winning days" in md and "best day" in md
    assert "dailys" not in md


def test_markdown_warns_that_sharpe_moves_with_position_size(tmp_path, monkeypatch):
    """The measured trap: the same 113 signals sized 3% to 40% of equity span
    a Sharpe of -9.59 to -2.41 while the P&L moves the other way, so ranking
    sizes by Sharpe inverts the answer."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk())), tmp_path / "x.pkl"))
    assert "position size" in md
    assert "inverts the answer" in md


def test_the_size_dependence_is_also_in_the_caveats(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_with_curve(_curve(_walk())), tmp_path / "x.pkl")
    assert any("capital at risk" in c for c in doc["caveats"])


def test_markdown_says_why_when_metrics_are_unavailable(tmp_path, monkeypatch):
    """An empty section would read as "no risk here"."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_result(equity_curve=[], fill_history=[],
                                       final_equity=None), tmp_path / "x.pkl"))
    assert "## Risk-adjusted performance" in md
    assert "Not measured" in md


def test_the_terminal_summary_shows_the_headline_metrics(
        reports, tmp_path, capsys, monkeypatch):
    """So a sweep can be read off the terminal without opening either file."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    path = reports / "engine_aaaa1111.pkl"
    _with_curve(_curve(_walk())).save(str(path))
    main(["aaaa", "--out", str(tmp_path / "out")])
    printed = capsys.readouterr().out
    assert "Sharpe" in printed and "max drawdown" in printed


def test_insight_agrees_with_the_shared_reporting_layer():
    """Same source, so the numbers must match what the tearsheet prints --
    otherwise there are two Sharpes in the project."""
    from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
    result = _with_curve(_curve(_walk()))
    mine = insight.performance(result)
    theirs = BacktestReport(result).metrics()
    assert mine["sharpe"] == pytest.approx(theirs["sharpe"], abs=1e-3)
    assert mine["cagr"] == pytest.approx(theirs["cagr"], abs=1e-3)
    assert mine["max_drawdown"] == pytest.approx(theirs["max_drawdown"], abs=1e-3)


def test_daily_and_round_trip_statistics_are_not_confused(tmp_path, monkeypatch):
    """quantstats also has win_rate and profit_factor, computed per DAY. This
    report already gives both per ROUND TRIP, which is the level a trader
    means. The daily ones are named for their unit; the ambiguous duplicates
    are left out entirely."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert "winning_periods_pct" in perf
    for ambiguous in ("win_rate", "profit_factor", "avg_win", "avg_loss",
                      "payoff_ratio", "consecutive_losses", "exposure",
                      "kelly_criterion"):
        assert ambiguous not in perf, ambiguous


# ══════════════════════════════════════════════════════════════════════════
#  The full tearsheet, mirrored
# ══════════════════════════════════════════════════════════════════════════
#
# An earlier version curated the metric list and left things out on judgement,
# including `exposure` -- which quantstats labels "Time in Market" in the HTML.
# An experimenter went looking for it and could not find it. The set is now
# mirrored from `qs.reports.metrics(mode="full")`, the same call the HTML is
# built from, so it cannot be short of the report it is compared against.

def test_time_in_market_is_present():
    """The specific metric that was reported missing. quantstats names it
    `exposure` in the API and "Time in Market" in the report."""
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert perf["time_in_market"] is not None
    assert 0.0 <= perf["time_in_market"] <= 1.0


def test_time_in_market_is_rendered_in_the_main_table(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk())), tmp_path / "x.pkl"))
    assert "time in market" in md


def test_the_tearsheet_mirrors_the_whole_report():
    """Not a count assertion against a magic number -- compared against the
    live quantstats call, so a version that adds a metric does not fail this
    and does not silently fall out of the report either."""
    import quantstats as qs
    result = _with_curve(_curve(_walk()))
    sheet = insight.performance(result)["tearsheet"]
    assert sheet["available"] is True
    expected = qs.reports.metrics(
        result.to_returns(), mode="full", display=False,
        periods_per_year=result._returns_periods_per_year)
    assert len(sheet["metrics"]) == len(expected)


def test_every_tearsheet_row_keeps_its_original_label():
    """So a reader can match a key back to the row in the HTML without
    reversing the key mangling."""
    sheet = insight.performance(_with_curve(_curve(_walk())))["tearsheet"]
    assert set(sheet["labels"]) == set(sheet["metrics"])
    assert all(sheet["labels"].values())


def test_the_metrics_an_experimenter_asks_for_by_name_are_all_there():
    sheet = insight.performance(_with_curve(_curve(_walk())))["tearsheet"]
    for key in ("time_in_market", "sharpe", "sortino", "calmar", "omega",
                "max_drawdown", "volatility_ann", "skew", "kurtosis",
                "kelly_criterion", "profit_factor", "win_days", "tail_ratio",
                "common_sense_ratio", "cpc_index", "serenity_index",
                "recovery_factor", "ulcer_index", "payoff_ratio",
                "gain_pain_ratio", "risk_of_ruin", "prob_sharpe_ratio",
                "smart_sharpe", "outlier_win_ratio", "best_day", "worst_day",
                "max_consecutive_wins", "max_consecutive_losses"):
        assert key in sheet["metrics"], key


@pytest.mark.parametrize("label, expected", [
    ("CAGR﹪", "cagr_pct"),
    ("Sortino/√2", "sortino_sqrt2"),
    ("Smart Sortino/√2", "smart_sortino_sqrt2"),
    ("3Y (ann.)", "3y_ann"),
    ("Prob. Sharpe Ratio", "prob_sharpe_ratio"),
    ("Expected Shortfall (cVaR)", "expected_shortfall_cvar"),
    ("Daily Value-at-Risk", "daily_value_at_risk"),
    ("Gain/Pain (1M)", "gain_pain_1m"),
    ("Avg. Up Month", "avg_up_month"),
    ("Time in Market", "time_in_market"),
])
def test_display_labels_become_usable_keys(label, expected):
    """The labels are written for a browser, so they carry a full-width
    percent sign, a square root, dots and slashes."""
    assert insight._metric_key(label) == expected


@pytest.mark.parametrize("raw, expected", [
    ("-", None), ("", None), ("nan", None), ("None", None),
    ("0.8", 0.8), ("-9.59", -9.59), ("2025-10-14", "2025-10-14"),
    (0.5, 0.5), (None, None),
])
def test_a_blank_cell_is_null_and_a_date_stays_a_date(raw, expected):
    assert insight._metric_value(raw) == expected


def _sinking(n=60):
    """A curve that ends underwater, so no drawdown ever completes -- which is
    what a losing run looks like and the case quantstats leaves blank."""
    return [100_000.0 - i * 50 for i in range(n)]


def test_max_drawdown_is_backfilled_rather_than_left_blank():
    """`metrics()` leaves that cell empty while the HTML shows a figure,
    because the block is built from drawdown_details() -- which is empty
    whenever the series never recovers. The cell a reader checks first should
    not be the empty one."""
    result = _with_curve(_curve(_sinking()))
    perf = insight.performance(result)
    assert perf["tearsheet"]["metrics"]["max_drawdown"] is not None
    assert perf["tearsheet"]["metrics"]["max_drawdown"] < 0
    # And it agrees with the figure computed directly for the core.
    assert perf["tearsheet"]["metrics"]["max_drawdown"] == pytest.approx(
        perf["max_drawdown"], abs=1e-4)


def test_drawdown_period_rows_stay_null_when_no_drawdown_ever_completed():
    """Not backfilled, deliberately: they describe a drawdown that ended, and
    a run still underwater at the close does not have one. Null is true, and
    inventing a number there would be worse than the blank."""
    sheet = insight.performance(_with_curve(_curve(_sinking())))["tearsheet"]
    for key in ("longest_dd_days", "max_dd_date", "avg_drawdown_days"):
        assert sheet["metrics"][key] is None, key


def test_completed_drawdowns_do_populate_the_period_rows():
    """The other half: a curve that recovers has real drawdown periods, so
    the blank above is about the data and not about the mirroring."""
    sheet = insight.performance(_with_curve(_curve(_walk())))["tearsheet"]
    assert sheet["metrics"]["longest_dd_days"] is not None


def test_the_tearsheet_carries_display_precision_not_full_precision():
    """Measured gotcha: a drawdown of -0.35% rounds to -0.00 at the two
    decimals the report prints, so the mirrored cell reads 0 while the core
    reads -0.003506. Faithful to the HTML, which is the point of it -- but a
    script must read the core, and that is why both layers exist."""
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert perf["max_drawdown"] == pytest.approx(-0.0035, abs=5e-4)
    assert perf["tearsheet"]["metrics"]["max_drawdown"] == 0


def test_the_tearsheet_is_json_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    doc = build(_with_curve(_curve(_walk())), tmp_path / "x.pkl")
    text = json.dumps(doc, default=str)
    for token in ("Infinity", "-Infinity", "NaN"):
        assert token not in text

    def reject(constant):
        raise AssertionError(f"illegal JSON constant {constant}")
    json.loads(text, parse_constant=reject)


def test_the_markdown_lists_every_tearsheet_row(tmp_path, monkeypatch):
    """So the file is a complete substitute for opening the HTML."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    result = _with_curve(_curve(_walk()))
    doc = build(result, tmp_path / "x.pkl")
    md = render_markdown(doc)
    assert "Every quantstats metric" in md
    assert "Time in Market" in md
    for label in doc["performance"]["tearsheet"]["labels"].values():
        assert label in md, label


def test_the_two_layers_are_documented_as_differing_in_precision(
        tmp_path, monkeypatch):
    """The tearsheet carries display precision; the core carries full. Saying
    so stops someone treating a -9.59 and a -9.589301 as a disagreement."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk())), tmp_path / "x.pkl"))
    assert "display precision" in md


def test_the_core_keeps_more_precision_than_the_tearsheet():
    perf = insight.performance(_with_curve(_curve(_walk())))
    core, mirrored = perf["sharpe"], perf["tearsheet"]["metrics"]["sharpe"]
    assert core == pytest.approx(mirrored, abs=0.01)
    assert len(str(core).split(".")[-1]) >= len(str(mirrored).split(".")[-1])


def test_the_tearsheet_explains_itself_when_it_cannot_be_built(monkeypatch):
    import quantstats as qs

    def boom(*a, **k):
        raise RuntimeError("quantstats exploded")

    monkeypatch.setattr(qs.reports, "metrics", boom)
    sheet = insight.performance(_with_curve(_curve(_walk())))["tearsheet"]
    assert sheet["available"] is False
    assert "quantstats exploded" in sheet["reason"]


def test_a_failed_tearsheet_does_not_take_the_core_with_it(monkeypatch):
    """Half a report beats none, and the core is what a sweep reads."""
    import quantstats as qs

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(qs.reports, "metrics", boom)
    perf = insight.performance(_with_curve(_curve(_walk())))
    assert perf["available"] is True
    assert perf["sharpe"] is not None


# ══════════════════════════════════════════════════════════════════════════
#  The other two tables the HTML report renders
# ══════════════════════════════════════════════════════════════════════════
#
# qs.reports.html builds three data tables, not one: {{metrics}}, {{dd_info}}
# and {{eoy_table}}. Mirroring only the first still left the document short of
# the report it is meant to replace.


def _recovering(n=400, seed=3):
    """Long enough to contain drawdowns that end, which is what makes a
    drawdown-periods table non-empty."""
    rng = random.Random(seed)
    value, out = 100_000.0, []
    for _ in range(n):
        value += -2.0 + rng.uniform(-60, 60)
        out.append(value)
    return out


def test_completed_drawdowns_are_listed_with_their_duration():
    """A max-drawdown scalar says how deep, never how long. On this curve the
    worst drawdown ran 316 days and no metric in the table says so."""
    periods = insight.performance(
        _with_curve(_curve(_recovering())))["drawdowns"]
    assert periods
    worst = periods[0]
    for key in ("start", "valley", "end", "days", "max_drawdown"):
        assert key in worst, key
    assert worst["days"] > 0


def test_drawdowns_are_ordered_worst_first():
    periods = insight.performance(
        _with_curve(_curve(_recovering())))["drawdowns"]
    depths = [d["max_drawdown"] for d in periods]
    assert depths == sorted(depths)


def test_the_drawdown_depth_uses_the_same_unit_as_the_rest_of_the_document():
    """quantstats is inconsistent: `max_drawdown()` is a fraction (-0.0116)
    and the `max drawdown` column of `drawdown_details` is a percent
    (-1.1586) -- exactly 100x apart. Unnormalised it renders as "-115.86%", a
    drawdown worse than total ruin."""
    result = _with_curve(_curve(_recovering()))
    perf = insight.performance(result)
    # The core rounds to six decimals; the table keeps what quantstats gave,
    # so they agree to the core's resolution rather than exactly.
    assert perf["drawdowns"][0]["max_drawdown"] == pytest.approx(
        perf["max_drawdown"], abs=1e-6)
    assert -1.0 <= perf["drawdowns"][0]["max_drawdown"] <= 0.0


def test_every_listed_drawdown_is_a_plausible_fraction():
    for dd in insight.performance(_with_curve(_curve(_recovering())))["drawdowns"]:
        assert -1.0 <= dd["max_drawdown"] <= 0.0, dd


def test_a_run_that_never_recovered_lists_no_drawdown_periods():
    assert insight.performance(_with_curve(_curve(_sinking())))["drawdowns"] == []


def test_the_markdown_explains_an_empty_drawdown_table(tmp_path, monkeypatch):
    """Rather than printing an empty table, which reads as "no drawdowns"."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_sinking())),
                               tmp_path / "x.pkl"))
    assert "### Drawdowns" in md
    assert "No drawdown ever ended" in md


def test_the_markdown_renders_the_drawdown_periods(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_recovering())),
                               tmp_path / "x.pkl"))
    assert "### Drawdowns" in md
    assert "valley" in md
    assert "-115" not in md, "a drawdown deeper than ruin was rendered"


# ── monthly / EOY returns ────────────────────────────────────────────────

def test_monthly_returns_carries_a_year_by_month_matrix():
    months = insight.performance(
        _with_curve(_curve(_recovering())))["monthly_returns"]
    assert months["available"] is True
    assert "JAN" in months["columns"] and "EOY" in months["columns"]
    assert len(months["columns"]) == 13
    assert months["years"]


def test_monthly_returns_values_are_fractions():
    months = insight.performance(
        _with_curve(_curve(_recovering())))["monthly_returns"]
    for year, cells in months["years"].items():
        for column, value in cells.items():
            if value is not None:
                assert -1.0 <= value <= 1.0, f"{year} {column} = {value}"


def test_the_markdown_renders_the_monthly_table(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_recovering())),
                               tmp_path / "x.pkl"))
    assert "### Returns by month" in md
    for month in ("JAN", "JUN", "DEC", "EOY"):
        assert month in md


def test_monthly_returns_says_why_when_it_has_no_month(tmp_path, monkeypatch):
    """A run shorter than a month has no row to show."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    md = render_markdown(build(_with_curve(_curve(_walk(4))), tmp_path / "x.pkl"))
    assert "### Returns by month" in md


def test_all_three_html_tables_are_present_together(tmp_path, monkeypatch):
    """The completeness claim, asserted in one place: the metrics table, the
    drawdown-periods table and the monthly/EOY table."""
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    perf = build(_with_curve(_curve(_recovering())),
                 tmp_path / "x.pkl")["performance"]
    assert perf["tearsheet"]["available"] and perf["tearsheet"]["metrics"]
    assert perf["drawdowns"]
    assert perf["monthly_returns"]["available"]


def test_the_extra_tables_are_json_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(insight.paths, "price_db_path",
                        lambda: tmp_path / "absent.db")
    text = json.dumps(build(_with_curve(_curve(_recovering())),
                            tmp_path / "x.pkl"), default=str)
    for token in ("Infinity", "-Infinity", "NaN"):
        assert token not in text

    def reject(constant):
        raise AssertionError(f"illegal JSON constant {constant}")
    json.loads(text, parse_constant=reject)
