"""The engine's clocks step and pace market time, and the replay window is checked.

ArenaX's control plane is a fake, and real time is a fake `time` module on the
engine, so pacing is checked without waiting on it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cjtrade.apps.CJTrade import main as engine

T0 = datetime(2026, 3, 2, 9, 1)


def minutes(*ms):
    return [T0 + timedelta(minutes=m) for m in ms]


class FakeMiddleware:
    def __init__(self, timeline=(), days=400):
        self.timeline, self.days = list(timeline), days
        self.set_to, self.origin = [], None

    def set_market_time(self, ts):
        self.set_to.append(ts)

    def get_timeline(self, symbols, start, end, interval):
        return list(self.timeline)

    def set_timeline_origin(self, **kw):
        self.origin = kw

    def get_config(self):
        return {"internal_config": {"backtest_duration_days": self.days}}


class FakeTime:
    """time.monotonic, set by hand."""

    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now


@pytest.fixture
def fake_time(monkeypatch):
    t = FakeTime()
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=t.monotonic))
    return t


class TestHumanDuration:
    @pytest.mark.parametrize("seconds,text", [
        (30, "30s"), (89, "89s"), (120, "2.0 min"), (2 * 3600, "2.0 hours"),
        (47 * 3600, "47.0 hours"), (3 * 86400, "3.0 days")])
    def test_a_duration_is_said_in_the_unit_a_person_would_use(self, seconds, text):
        assert engine._human_duration(seconds) == text


class TestPaceSummary:
    def test_no_speed_is_flat_out(self):
        assert engine._pace_summary(minutes(0, 1), None) == "flat out (no pacing)"
        assert engine._pace_summary(minutes(0, 1), 0) == "flat out (no pacing)"

    def test_a_timeline_inside_one_session_reports_only_the_requested_rate(self):
        text = engine._pace_summary(minutes(0, 1, 2), 60)
        assert text == "60x within a session → about 3s of wall clock"

    def test_a_timeline_across_a_closed_market_also_reports_the_end_to_end_rate(self):
        stamps = [T0, T0 + timedelta(hours=19, minutes=30)]
        text = engine._pace_summary(stamps, 60)
        # 2 bars at 60x cost 2s of wall clock for 19.5h of market time.
        assert "spans 20h of market time, so ~35,100x end to end" in text


class TestAssertServerDataCovers:
    def test_a_server_that_does_not_say_how_many_days_it_holds_is_not_fatal(self):
        mw = FakeMiddleware()
        mw.get_config = lambda: None
        engine._assert_server_data_covers(mw, minutes(0, 1))

    def test_a_replay_ending_on_the_servers_last_bar_is_covered(self):
        stamps = [T0, datetime(2026, 3, 3, 9, 0)]
        engine._assert_server_data_covers(FakeMiddleware(days=1), stamps)

    def test_a_replay_running_past_the_servers_data_is_refused_with_both_fixes(self):
        stamps = [T0, datetime(2026, 3, 3, 13, 30)]
        with pytest.raises(RuntimeError) as err:
            engine._assert_server_data_covers(FakeMiddleware(days=1), stamps)
        assert "--days=1 or lower" in str(err.value)
        assert "AX_BACKTEST_DURATION_DAYS=2" in str(err.value)


class TestReplayClockForServer:
    def test_a_middleware_that_cannot_set_the_clock_is_refused(self):
        mw = SimpleNamespace(get_timeline=lambda *a: minutes(0))
        with pytest.raises(RuntimeError, match="set_market_time"):
            engine.ReplayClock.for_server(mw, ["2330"], "2026-03-02", "2026-03-03")

    def test_a_middleware_without_a_timeline_is_refused(self):
        mw = SimpleNamespace(set_market_time=lambda ts: None)
        with pytest.raises(RuntimeError, match="get_timeline"):
            engine.ReplayClock.for_server(mw, ["2330"], "2026-03-02", "2026-03-03")

    def test_a_window_with_no_bars_is_refused(self):
        with pytest.raises(ValueError, match="no bars"):
            engine.ReplayClock.for_server(FakeMiddleware(), ["2330"],
                                          "2026-03-02", "2026-03-03")

    def test_the_server_is_parked_on_the_first_bar_without_preloading(self):
        mw = FakeMiddleware(timeline=minutes(0, 1, 2))
        clock = engine.ReplayClock.for_server(mw, ["2330"], "2026-03-02",
                                              "2026-03-03", speed=600)
        assert mw.origin == {"mock_init_time": T0.isoformat(),
                             "auto_start_progress": False,
                             "auto_preload_data": False}
        assert mw.set_to == [T0]
        assert (clock.now, clock.speed, clock.timestamps) == (T0, 600, minutes(0, 1, 2))

    def test_a_window_the_server_does_not_cover_is_refused(self):
        mw = FakeMiddleware(timeline=[T0, T0 + timedelta(days=3)], days=1)
        with pytest.raises(RuntimeError, match="past it"):
            engine.ReplayClock.for_server(mw, ["2330"], "2026-03-02", "2026-03-06")


class TestReplayClockSleep:
    def test_each_sleep_steps_to_the_next_bar_and_moves_the_server_there(self):
        mw = FakeMiddleware()
        clock = engine.ReplayClock(mw, minutes(0, 1, 2))
        asyncio.run(clock.sleep(60))
        assert clock.now == minutes(1)[0] and not clock.finished
        asyncio.run(clock.sleep(60))
        assert clock.finished
        assert mw.set_to == minutes(0, 1, 2)

    def test_a_gap_in_the_bars_is_crossed_in_one_sleep(self):
        clock = engine.ReplayClock(FakeMiddleware(), minutes(0, 1, 90, 91))
        asyncio.run(clock.sleep(120))
        assert clock.now == minutes(90)[0]

    def test_a_sleep_shorter_than_a_bar_still_moves_to_the_next_bar(self):
        clock = engine.ReplayClock(FakeMiddleware(), minutes(0, 5))
        asyncio.run(clock.sleep(1))
        assert clock.now == minutes(5)[0]

    def test_sleeping_on_the_last_bar_stays_there(self):
        mw = FakeMiddleware()
        clock = engine.ReplayClock(mw, minutes(0))
        asyncio.run(clock.sleep(60))
        assert clock.finished and clock.now == T0 and mw.set_to == [T0, T0]

    def test_a_paced_replay_waits_out_the_bars_budget(self, fake_time, monkeypatch):
        waits = []

        async def fake_sleep(s):
            waits.append(s)
        clock = engine.ReplayClock(FakeMiddleware(), minutes(0, 1, 2), speed=60)
        monkeypatch.setattr(engine.asyncio, "sleep", fake_sleep)
        asyncio.run(clock.sleep(60))
        # Half the budget already spent on this bar's work: only the rest is slept.
        fake_time.now += 0.5
        asyncio.run(clock.sleep(60))
        assert waits == [1.0, 1.5]

    def test_a_replay_that_falls_behind_says_so_and_rebaselines(self, fake_time, monkeypatch):
        async def fake_sleep(_s):
            pass
        monkeypatch.setattr(engine.asyncio, "sleep", fake_sleep)
        clock = engine.ReplayClock(FakeMiddleware(), minutes(*range(5)), speed=60)
        asyncio.run(clock.sleep(60))          # sets the deadline at now + 1s
        fake_time.now += 10
        asyncio.run(clock.sleep(60))          # 9s late: logged, counters reset
        assert (clock._behind_bars, clock._last_behind_log, clock._deadline) == \
            (0, fake_time.now, fake_time.now)
        fake_time.now += 3
        asyncio.run(clock.sleep(60))          # late again within 5s: only counted
        assert clock._behind_bars == 1
        assert clock._behind_worst_ms == pytest.approx(2000)


class TestScaledClock:
    def test_a_server_that_reports_no_time_is_refused(self):
        mw = SimpleNamespace(get_market_time=lambda: None)
        with pytest.raises(RuntimeError, match="returned nothing"):
            engine.ScaledClock.for_server(mw)

    def test_it_never_finishes(self):
        assert engine.ScaledClock(10).finished is False

    def test_it_sleeps_market_seconds_divided_by_the_servers_speed(self, fake_time, monkeypatch):
        waits = []

        async def fake_sleep(s):
            waits.append(s)
        monkeypatch.setattr(engine.asyncio, "sleep", fake_sleep)
        clock = engine.ScaledClock(30.0)
        asyncio.run(clock.sleep(60))
        asyncio.run(clock.sleep(60))
        assert waits == [2.0, 4.0]

    def test_falling_behind_rebaselines_instead_of_accruing_debt(self, fake_time, monkeypatch):
        waits = []

        async def fake_sleep(s):
            waits.append(s)
        monkeypatch.setattr(engine.asyncio, "sleep", fake_sleep)
        clock = engine.ScaledClock(60.0)
        asyncio.run(clock.sleep(60))
        fake_time.now += 30
        asyncio.run(clock.sleep(60))
        assert waits == [1.0] and clock._deadline == fake_time.now


class TestRealtimeClock:
    def test_it_sleeps_the_market_seconds_in_real_seconds(self, monkeypatch):
        waits = []

        async def fake_sleep(s):
            waits.append(s)
        monkeypatch.setattr(engine.asyncio, "sleep", fake_sleep)
        clock = engine.RealtimeClock()
        asyncio.run(clock.sleep(60))
        assert waits == [60] and clock.finished is False
