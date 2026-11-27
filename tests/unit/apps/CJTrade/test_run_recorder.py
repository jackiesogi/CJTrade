"""RunRecorder keeps the equity curve and the end-of-run report is assembled from it.

The fill history comes from a fake control plane and the tearsheet renderer is
a fake; files go under a temporary CJTRADE_HOME.
"""
from __future__ import annotations

import json
import pickle
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cjtrade.apps.CJTrade import main as engine
from cjtrade.pkgs.models.backtest import BacktestResult
from cjtrade.pkgs.models.position import Position

T0 = datetime(2026, 3, 2, 9, 1)


class TestObserve:
    def test_the_first_sample_sets_the_runs_start_in_market_time(self):
        rec = engine.RunRecorder("s1", 1000)
        rec.observe(T0.replace(second=30), 1000.004)
        assert rec.start_time == "2026-03-02T09:01:30"
        assert rec.equity_curve == [{"time": "2026-03-02T09:01:00", "value": 1000.0}]

    def test_at_most_one_sample_is_kept_per_market_minute(self):
        rec = engine.RunRecorder("s1", 1000)
        rec.observe(T0, 1)
        rec.observe(T0.replace(second=59), 2)
        rec.observe(T0 + timedelta(minutes=1), 3)
        assert [s["value"] for s in rec.equity_curve] == [1, 3]

    def test_a_sample_without_a_market_time_is_stamped_now(self):
        rec = engine.RunRecorder("s1", 1000)
        rec.observe(None, 5)
        assert rec.start_time is not None and len(rec.equity_curve) == 1


class TestJournal:
    def test_every_kept_sample_is_appended_to_the_journal(self, tmp_path):
        path = tmp_path / "e.jsonl"
        rec = engine.RunRecorder("s1", 1000, journal_path=path)
        rec.observe(T0, 1)
        rec.observe(T0, 1)
        rec.observe(T0 + timedelta(minutes=1), 2)
        rec.close()
        assert engine.RunRecorder.read_journal(path) == rec.equity_curve

    def test_close_is_safe_to_call_twice(self, tmp_path):
        rec = engine.RunRecorder("s1", 1000, journal_path=tmp_path / "e.jsonl")
        rec.close()
        rec.close()
        assert rec._journal is None

    def test_a_journal_that_cannot_be_opened_still_leaves_a_run(self, tmp_path):
        rec = engine.RunRecorder("s1", 1000, journal_path=tmp_path)  # a directory
        rec.observe(T0, 1)
        assert rec._journal is None and len(rec.equity_curve) == 1

    def test_a_journal_write_that_fails_drops_the_journal_not_the_sample(self, tmp_path):
        rec = engine.RunRecorder("s1", 1000, journal_path=tmp_path / "e.jsonl")
        rec._journal.close()

        class Broken:
            def write(self, _):
                raise OSError("disk full")
        rec._journal = Broken()
        rec.observe(T0, 1)
        assert rec._journal is None and len(rec.equity_curve) == 1

    def test_reading_skips_blank_lines_and_a_torn_last_line(self, tmp_path):
        path = tmp_path / "e.jsonl"
        path.write_text(json.dumps({"time": "a", "value": 1}) + "\n\n"
                        + json.dumps({"time": "b", "value": 2}) + "\n"
                        + '{"time": "c", "val')
        assert engine.RunRecorder.read_journal(path) == \
            [{"time": "a", "value": 1}, {"time": "b", "value": 2}]


class FakeControlPlane:
    def __init__(self, state):
        self.state, self.asked = state, []

    def get_backtest_state(self, session_id):
        self.asked.append(session_id)
        return self.state


def client(ctrl, balance=800.0, positions=()):
    return SimpleNamespace(
        control_plane=ctrl,
        get_account_state=lambda: SimpleNamespace(balance=balance,
                                                  positions=list(positions)))


class TestBuildResult:
    def test_a_broker_without_a_control_plane_has_no_report(self):
        assert engine.RunRecorder("s1", 1000).build_result(client(None)) is None

    def test_a_server_with_no_fill_history_has_no_report(self):
        assert engine.RunRecorder("s1", 1000).build_result(
            client(FakeControlPlane(None))) is None

    def test_the_result_carries_this_sessions_fills_and_the_held_value(self):
        fills = [{"time": "t", "symbol": "2330", "action": "BUY", "quantity": 1,
                  "price": 200.0}]
        ctrl = FakeControlPlane({"fill_history": fills})
        rec = engine.RunRecorder("s1", 1000)
        rec.observe(T0, 1000)
        res = rec.build_result(client(ctrl, 800.0, [
            Position("2330", 1, 200.0, 210.0, 210.0)]))
        assert ctrl.asked == ["s1"]
        assert (res.initial_balance, res.final_balance, res.final_equity,
                res.fill_history, res.session_id, res.start_time) == \
            (1000, 800.0, 1010.0, fills, "s1", T0.isoformat())
        assert res.equity_curve == rec.equity_curve
        assert res.equity_curve is not rec.equity_curve


class FakeReport:
    made: list = []

    def __init__(self, result):
        self.result, self.calls = result, []
        FakeReport.made.append(self)

    def summary(self):
        self.calls.append("summary")

    def print_round_trips(self):
        self.calls.append("round_trips")

    def full_report(self, path, open_browser, title):
        self.calls.append(("html", path, open_browser, title))
        if self.result.equity_curve == []:
            raise ValueError("needs two samples")


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("CJTRADE_HOME", str(tmp_path))
    FakeReport.made = []
    monkeypatch.setattr(engine, "BacktestReport", FakeReport)
    return engine.paths.reports_dir()


def backtest(session_id="abcdef1234", curve=({"time": "t", "value": 1},)):
    return BacktestResult(initial_balance=1000, final_balance=1000,
                          equity_curve=list(curve), fill_history=[],
                          session_id=session_id)


class TestPrintRunReport:
    def test_the_summary_round_trips_pickle_and_tearsheet_are_all_produced(self, reports):
        engine.print_run_report(backtest(), open_browser=False)
        [report] = FakeReport.made
        stem = reports / "engine_abcdef12"
        assert report.calls == ["summary", "round_trips",
                                ("html", f"{stem}.html", False,
                                 "Trading engine — abcdef12")]
        with open(f"{stem}.pkl", "rb") as fh:
            assert pickle.load(fh).session_id == "abcdef1234"

    def test_a_result_without_a_session_is_filed_as_run(self, reports):
        engine.print_run_report(backtest(session_id=None), open_browser=False)
        assert (reports / "engine_run.pkl").exists()

    def test_a_tearsheet_that_cannot_be_drawn_does_not_lose_the_pickle(self, reports):
        engine.print_run_report(backtest(curve=()), open_browser=False)
        assert (reports / "engine_abcdef12.pkl").exists()

    def test_a_pickle_that_cannot_be_written_still_draws_the_tearsheet(self, reports):
        res = backtest()
        res.save = lambda path: (_ for _ in ()).throw(OSError("read-only"))
        engine.print_run_report(res, open_browser=False)
        assert FakeReport.made[0].calls[-1][0] == "html"
