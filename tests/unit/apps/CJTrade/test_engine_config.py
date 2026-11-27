"""The engine reads its roster, its form answers and its clock choice correctly.

No form is shown and no broker is reached: FormEngine, the account client and
ArenaX's control plane are fakes.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from cjtrade.apps.CJTrade import main as engine

T0 = datetime(2026, 3, 2, 9, 1)


def write_roster(tmp_path, payload) -> str:
    path = tmp_path / "roster.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")
    return f"{engine.ROSTER_FLAG}{path}"


class TestRosterFromArgv:
    def test_no_roster_flag_means_the_built_in_roster(self):
        assert engine.roster_from_argv(["cjtrade", "--mode=backtest"]) is None

    def test_an_empty_roster_path_means_the_built_in_roster(self):
        assert engine.roster_from_argv(["cjtrade", "--roster="]) is None

    def test_sys_argv_is_read_when_no_argv_is_given(self, tmp_path, monkeypatch):
        flag = write_roster(tmp_path, [{"bot_id": "B1", "script": "bot_b.py",
                                        "symbol": "2357"}])
        monkeypatch.setattr(engine.sys, "argv", ["cjtrade", flag])
        assert engine.roster_from_argv() == [("B1", "bot_b.py", "2357", ())]

    def test_each_entry_becomes_a_tuple_with_its_extra_argv(self, tmp_path):
        flag = write_roster(tmp_path, [
            {"bot_id": "U1", "script": "bot_custom.py", "symbol": 2317,
             "extra": ["/s/strategy.py", 7]},
            {"bot_id": "B1", "script": "bot_b.py", "symbol": "2357", "extra": None},
        ])
        assert engine.roster_from_argv([flag]) == [
            ("U1", "bot_custom.py", "2317", ("/s/strategy.py", "7")),
            ("B1", "bot_b.py", "2357", ()),
        ]

    @pytest.mark.parametrize("payload", [{"bot_id": "B1"}, [], "\"bots\""])
    def test_a_roster_that_is_not_a_non_empty_list_is_refused(self, tmp_path, payload):
        flag = write_roster(tmp_path, payload)
        with pytest.raises(ValueError, match="non-empty list"):
            engine.roster_from_argv([flag])

    def test_an_entry_that_is_not_an_object_is_refused(self, tmp_path):
        flag = write_roster(tmp_path, [["B1", "bot_b.py", "2357"]])
        with pytest.raises(ValueError, match=r"\[0\] is not an object"):
            engine.roster_from_argv([flag])

    def test_an_entry_missing_a_field_names_the_field(self, tmp_path):
        flag = write_roster(tmp_path, [{"bot_id": "B1", "script": "bot_b.py"}])
        with pytest.raises(ValueError, match="has no 'symbol'"):
            engine.roster_from_argv([flag])

    def test_two_bots_on_one_id_are_refused(self, tmp_path):
        bot = {"bot_id": "B1", "script": "bot_b.py", "symbol": "2357"}
        flag = write_roster(tmp_path, [bot, dict(bot, symbol="2317")])
        with pytest.raises(ValueError, match="'B1' twice"):
            engine.roster_from_argv([flag])

    @pytest.mark.parametrize("script", ["/bin/sh", "../bot_b.py", "evil.py",
                                        "bot_b"])
    def test_a_script_that_is_not_one_of_the_engines_bots_is_refused(self, tmp_path, script):
        flag = write_roster(tmp_path, [{"bot_id": "B1", "script": script,
                                        "symbol": "2357"}])
        with pytest.raises(ValueError, match="not a bot script"):
            engine.roster_from_argv([flag])

    def test_a_missing_roster_file_raises_rather_than_falling_back(self, tmp_path):
        with pytest.raises(OSError):
            engine.roster_from_argv([f"{engine.ROSTER_FLAG}{tmp_path / 'nope.json'}"])

    def test_a_roster_that_is_not_json_raises(self, tmp_path):
        flag = write_roster(tmp_path, "[{not json")
        with pytest.raises(json.JSONDecodeError):
            engine.roster_from_argv([flag])


class TestArenaxPort:
    def test_each_mode_has_its_own_default_port(self, monkeypatch):
        monkeypatch.delenv("ARENAX_PORT", raising=False)
        assert [engine.arenax_port(m) for m in ("demo", "backtest", "paper")] == \
            [8801, 8802, 8803]

    def test_an_unknown_mode_falls_back_to_the_backtest_port(self, monkeypatch):
        monkeypatch.delenv("ARENAX_PORT", raising=False)
        assert engine.arenax_port("real") == 8802

    def test_arenax_port_in_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("ARENAX_PORT", "19001")
        assert engine.arenax_port("demo") == 19001


class TestAt:
    def test_a_known_moment_opens_a_log_line(self):
        assert engine._at(T0) == "@2026-03-02 09:01 "

    def test_an_unknown_moment_adds_nothing(self):
        assert engine._at(None) == ""


class FakeForm:
    answers: dict = {}

    def __init__(self, schema, renderer):
        self.schema, self.renderer = schema, renderer

    def run(self):
        return dict(self.answers)


@pytest.fixture
def form(monkeypatch):
    monkeypatch.setattr(engine, "FormEngine", FakeForm)
    return FakeForm


class TestLoadConfig:
    def test_answers_are_coerced_into_the_config(self, form):
        form.answers = {"broker": "arenax", "mode": "paper",
                        "watch_list": " 0050, 2317 ,,", "fund": "500000",
                        "days": "30", "playback_speed": "60",
                        "start_date": "2025-09-01"}
        cfg = engine.load_config()
        assert cfg == engine.EngineConfig(
            broker="arenax", backend_mode="paper", symbols=["0050", "2317"],
            initial_balance=500000.0, duration_days=30, playback_speed=60.0,
            start_date="2025-09-01")
        assert isinstance(cfg.duration_days, int)

    def test_no_answers_give_the_defaults(self, form):
        form.answers = {}
        cfg = engine.load_config()
        assert (cfg.broker, cfg.backend_mode, cfg.symbols, cfg.initial_balance,
                cfg.duration_days, cfg.playback_speed, cfg.start_date) == \
            ("arenax", "backtest", [], 1_000_000, 365, 1.0, None)

    def test_a_speed_of_zero_is_kept_rather_than_replaced_by_the_default(self, form):
        form.answers = {"playback_speed": "0", "fund": 0}
        cfg = engine.load_config()
        assert (cfg.playback_speed, cfg.initial_balance) == (0.0, 0.0)

    def test_blank_answers_count_as_unanswered(self, form):
        form.answers = {"playback_speed": "  ", "days": "", "start_date": "  "}
        cfg = engine.load_config()
        assert (cfg.playback_speed, cfg.duration_days, cfg.start_date) == \
            (1.0, 365, None)

    def test_the_form_is_asked_on_the_cli_renderer_with_the_given_schema(self, form, monkeypatch):
        seen = []
        monkeypatch.setattr(FakeForm, "run", lambda self: seen.append(
            (self.schema, self.renderer)) or {})
        engine.load_config(schema=engine.Path("/x/form.toml"))
        assert seen == [("/x/form.toml", "cli")]


def config(**kw) -> engine.EngineConfig:
    base = dict(broker="arenax", backend_mode="backtest", symbols=["2330"],
                initial_balance=1e6, duration_days=30, playback_speed=60.0,
                start_date="2025-09-01")
    return engine.EngineConfig(**{**base, **kw})


class TestEngineConfig:
    @pytest.mark.parametrize("mode,live", [("paper", True), ("real", True),
                                           ("backtest", False), ("demo", False)])
    def test_only_paper_and_real_track_the_wall_clock(self, mode, live):
        assert config(backend_mode=mode).is_live is live


class FakeMiddleware:
    """ArenaX's control plane, as far as the clocks use it."""

    def __init__(self, timeline=None, days=400, speed=10.0):
        self.timeline = [T0, T0.replace(minute=2)] if timeline is None else timeline
        self.days, self.speed = days, speed
        self.calls = []

    def get_market_time(self):
        return {"playback_speed": self.speed}

    def get_timeline(self, symbols, start, end, interval):
        self.calls.append(("timeline", symbols, start, end, interval))
        return list(self.timeline)

    def set_timeline_origin(self, **kw):
        self.calls.append(("origin", kw))

    def set_market_time(self, ts):
        self.calls.append(("set", ts))

    def get_config(self):
        return {"internal_config": {"backtest_duration_days": self.days}}


class FakeClient:
    def __init__(self, mw):
        self.control_plane = mw

    def get_broker_name(self):
        return "sinopac"

    def get_market_time(self):
        return {"mock_init_time": datetime(2025, 7, 1, 9, 0)}


class TestBuildClock:
    def test_realtime_needs_no_broker_at_all(self):
        assert isinstance(engine.build_clock(None, "realtime", config()),
                          engine.RealtimeClock)

    def test_a_simulated_clock_on_a_broker_without_a_control_plane_is_refused(self):
        with pytest.raises(RuntimeError, match="'sinopac' has no control plane"):
            engine.build_clock(FakeClient(None), "replay", config())

    def test_scaled_takes_its_speed_from_the_server(self):
        clock = engine.build_clock(FakeClient(FakeMiddleware(speed=12)), "scaled",
                                   config(playback_speed=99))
        assert isinstance(clock, engine.ScaledClock) and clock.speed == 12.0

    def test_replay_asks_for_a_half_open_window_of_duration_days(self):
        mw = FakeMiddleware()
        clock = engine.build_clock(FakeClient(mw), "replay",
                                   config(start_date="2025-09-01", duration_days=30))
        assert mw.calls[0] == ("timeline", ["2330"], "2025-09-01", "2025-10-01", "1m")
        assert isinstance(clock, engine.ReplayClock) and clock.speed == 60.0

    def test_replay_without_a_start_date_uses_the_servers_origin(self):
        mw = FakeMiddleware()
        engine.build_clock(FakeClient(mw), "replay",
                           config(start_date=None, duration_days=2))
        assert mw.calls[0][2:4] == ("2025-07-01", "2025-07-03")

    def test_replay_at_speed_zero_runs_flat_out(self):
        clock = engine.build_clock(FakeClient(FakeMiddleware()), "replay",
                                   config(playback_speed=0))
        assert clock.speed is None

    def test_an_unknown_clock_name_is_refused(self):
        with pytest.raises(ValueError, match="unknown clock: 'lunar'"):
            engine.build_clock(FakeClient(FakeMiddleware()), "lunar", config())
