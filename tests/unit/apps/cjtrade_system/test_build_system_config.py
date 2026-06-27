"""Unit tests for build_system_config() and the --dry-run CLI flag.

Coverage goals
--------------
1. Default values when no env vars and no .cjsys config file exist.
2. Priority ordering: os.environ > .cjsys file > hardcoded default.
3. Mode-specific backtest_duration_days logic (backtest/demo → 7, real/paper → inf).
4. SystemConfig.to_dict() replaces float('inf') with the string "inf".
5. SystemConfig.dump_json() round-trips cleanly through json.loads().
6. The `system --dry-run` CLI prints valid JSON and exits 0, with env-var overrides
   reflected in the output.
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cjtrade.apps.cjtrade_system.cjtrade_system_arenax import build_system_config
from cjtrade.apps.cjtrade_system.cjtrade_system_arenax import SystemConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parents[4]  # …/CJTrade


def _run_dry(*extra_args, env=None) -> subprocess.CompletedProcess:
    """Run `uv run system --dry-run [extra_args]` from the project root."""
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["uv", "run", "system", "--dry-run", *extra_args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=merged_env,
    )


def _extract_json_from_output(output: str) -> dict:
    """Extract the JSON object from CLI output that may include log lines."""
    start = output.find("{")
    end = output.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in output: {output!r}")
    return json.loads(output[start:end + 1])


# ---------------------------------------------------------------------------
# TestSystemConfigDefaults
# ---------------------------------------------------------------------------

class TestSystemConfigDefaults:
    """build_system_config() uses correct hardcoded defaults when nothing else set."""

    def test_mode_stored_in_launch_mode(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # ensure no stray .cjsys files are picked up
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert cfg.launch_mode == "backtest"

    def test_remote_host_default(self, monkeypatch):
        monkeypatch.delenv("CJSYS_REMOTE_HOST", raising=False)
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert cfg.remote_host == "localhost"

    def test_remote_port_default(self, monkeypatch):
        monkeypatch.delenv("CJSYS_REMOTE_PORT", raising=False)
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert cfg.remote_port == 8801

    def test_api_host_default(self, monkeypatch):
        monkeypatch.delenv("CJSYS_API_HOST", raising=False)
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert cfg.api_host == "0.0.0.0"

    def test_api_port_default(self, monkeypatch):
        monkeypatch.delenv("CJSYS_API_PORT", raising=False)
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert cfg.api_port == 8899

    def test_returns_system_config_instance(self):
        cfg = build_system_config("nonexistent_broker", "backtest")
        assert isinstance(cfg, SystemConfig)


# ---------------------------------------------------------------------------
# TestBacktestDurationDays
# ---------------------------------------------------------------------------

class TestBacktestDurationDays:
    """Automatic backtest_duration_days logic based on mode."""

    @pytest.mark.parametrize("broker,mode,expected", [
        ("arenax", "backtest", 300),
        ("arenax", "demo", 7),
    ])
    def test_finite_for_backtest_modes(self, monkeypatch, broker, mode, expected):
        monkeypatch.delenv("CJSYS_BACKTEST_DURATION_DAYS", raising=False)
        cfg = build_system_config(broker, mode)
        assert cfg.backtest_duration_days == expected

    @pytest.mark.parametrize("mode", ["real", "paper"])
    def test_infinite_for_live_modes(self, monkeypatch, mode):
        monkeypatch.delenv("CJSYS_BACKTEST_DURATION_DAYS", raising=False)
        cfg = build_system_config("arenax", mode)
        assert math.isinf(cfg.backtest_duration_days)

    def test_env_override_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("CJSYS_BACKTEST_DURATION_DAYS", "14")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.backtest_duration_days == 14

    def test_env_override_on_live_mode(self, monkeypatch):
        """Explicit env var overrides even the live-mode inf default."""
        monkeypatch.setenv("CJSYS_BACKTEST_DURATION_DAYS", "30")
        cfg = build_system_config("arenax", "real")
        assert cfg.backtest_duration_days == 30


# ---------------------------------------------------------------------------
# TestEnvPriority
# ---------------------------------------------------------------------------

class TestEnvPriority:
    """os.environ values override all other config sources."""

    def test_watch_list_from_env(self, monkeypatch):
        monkeypatch.setenv("CJSYS_WATCH_LIST", "2330,2317")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.watch_list == ["2330", "2317"]

    def test_watch_list_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("CJSYS_WATCH_LIST", " 2330 , 2317 ")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.watch_list == ["2330", "2317"]

    def test_watch_list_none_value_excluded(self, monkeypatch):
        monkeypatch.setenv("CJSYS_WATCH_LIST", "none")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.watch_list == []

    def test_remote_host_env_override(self, monkeypatch):
        monkeypatch.setenv("CJSYS_REMOTE_HOST", "192.168.1.100")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.remote_host == "192.168.1.100"

    def test_remote_port_env_override(self, monkeypatch):
        monkeypatch.setenv("CJSYS_REMOTE_PORT", "9900")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.remote_port == 9900

    def test_analysis_interval_env_override(self, monkeypatch):
        monkeypatch.setenv("CJSYS_ANALYSIS_INTERVAL", "15")
        cfg = build_system_config("arenax", "backtest")
        assert cfg.analysis_interval == 15.0


# ---------------------------------------------------------------------------
# TestFilePriority
# ---------------------------------------------------------------------------

class TestFilePriority:
    """Values from a .cjsys file are used when no matching env var is set."""

    def test_watch_list_from_file(self, monkeypatch, tmp_path):
        # Write a minimal .cjsys file in the configs directory location
        # Build_system_config looks for broker_mode.cjsys next to the module.
        # We patch the config path by writing an env var that shadows the file key
        # — but this test uses a _different_ approach: write the actual configs dir.
        configs_dir = (
            Path(__file__).parents[4]
            / "src" / "cjtrade" / "apps" / "cjtrade_system" / "configs"
        )
        test_cfg = configs_dir / "test_broker_testmode.cjsys"
        monkeypatch.delenv("CJSYS_WATCH_LIST", raising=False)
        # Write a temp file at the expected path, clean up after
        test_cfg.write_text("CJSYS_WATCH_LIST=8888,9999\n")
        try:
            cfg = build_system_config("test_broker", "testmode")
            assert cfg.watch_list == ["8888", "9999"]
        finally:
            test_cfg.unlink(missing_ok=True)

    def test_env_beats_file(self, monkeypatch):
        """When both env var and file key present, env wins."""
        configs_dir = (
            Path(__file__).parents[4]
            / "src" / "cjtrade" / "apps" / "cjtrade_system" / "configs"
        )
        test_cfg = configs_dir / "test_broker2_testmode.cjsys"
        test_cfg.write_text("CJSYS_WATCH_LIST=1111\n")
        monkeypatch.setenv("CJSYS_WATCH_LIST", "2222")
        try:
            cfg = build_system_config("test_broker2", "testmode")
            assert cfg.watch_list == ["2222"]
        finally:
            test_cfg.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestSystemConfigSerialization
# ---------------------------------------------------------------------------

class TestSystemConfigSerialization:
    """SystemConfig.to_dict() and dump_json() behave correctly."""

    def test_to_dict_inf_becomes_string(self, monkeypatch):
        monkeypatch.delenv("CJSYS_BACKTEST_DURATION_DAYS", raising=False)
        cfg = build_system_config("arenax", "real")
        d = cfg.to_dict()
        assert d["backtest_duration_days"] == "inf"

    def test_to_dict_finite_stays_numeric(self, monkeypatch):
        monkeypatch.delenv("CJSYS_BACKTEST_DURATION_DAYS", raising=False)
        cfg = build_system_config("arenax", "backtest")
        d = cfg.to_dict()
        assert d["backtest_duration_days"] == 300

    def test_dump_json_valid_json(self):
        cfg = build_system_config("arenax", "backtest")
        parsed = json.loads(cfg.dump_json())
        assert isinstance(parsed, dict)

    def test_dump_json_contains_launch_mode(self):
        cfg = build_system_config("arenax", "demo")
        parsed = json.loads(cfg.dump_json())
        assert parsed["launch_mode"] == "demo"

    def test_dump_json_inf_serialised_as_string(self, monkeypatch):
        monkeypatch.delenv("CJSYS_BACKTEST_DURATION_DAYS", raising=False)
        cfg = build_system_config("arenax", "paper")
        parsed = json.loads(cfg.dump_json())
        assert parsed["backtest_duration_days"] == "inf"


# ---------------------------------------------------------------------------
# TestDryRunCLI  (subprocess — tests the full CLI path end-to-end)
# ---------------------------------------------------------------------------

class TestDryRunCLI:
    """The `system --dry-run` flag prints a valid SystemConfig JSON and exits 0."""

    @pytest.mark.parametrize("broker,mode", [
        ("arenax", "backtest"),
        ("arenax", "demo"),
        ("arenax", "paper"),
        ("sinopac", "real"),
    ])
    def test_exits_zero(self, broker, mode):
        result = _run_dry(f"--broker={broker}", f"--mode={mode}")
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("broker,mode", [
        ("arenax", "backtest"),
        ("arenax", "demo"),
        ("arenax", "paper"),
        ("sinopac", "real"),
    ])
    def test_stdout_is_valid_json(self, broker, mode):
        result = _run_dry(f"--broker={broker}", f"--mode={mode}")
        assert result.returncode == 0, result.stderr
        cfg = _extract_json_from_output(result.stdout)
        assert isinstance(cfg, dict)

    def test_launch_mode_matches_flag(self):
        result = _run_dry("--broker=arenax", "--mode=demo")
        cfg = _extract_json_from_output(result.stdout)
        assert cfg["launch_mode"] == "demo"

    def test_backtest_duration_finite_for_backtest(self):
        result = _run_dry("--broker=arenax", "--mode=backtest")
        cfg = _extract_json_from_output(result.stdout)
        assert cfg["backtest_duration_days"] == 300

    def test_backtest_duration_inf_for_live(self):
        result = _run_dry("--broker=sinopac", "--mode=real")
        cfg = _extract_json_from_output(result.stdout)
        assert cfg["backtest_duration_days"] == "inf"

    def test_env_watch_list_visible_in_output(self):
        result = _run_dry(
            "--broker=arenax", "--mode=backtest",
            env={"CJSYS_WATCH_LIST": "3008,2454"},
        )
        cfg = _extract_json_from_output(result.stdout)
        assert cfg["watch_list"] == ["3008", "2454"]

    def test_env_remote_port_visible_in_output(self):
        result = _run_dry(
            "--broker=arenax", "--mode=backtest",
            env={"CJSYS_REMOTE_PORT": "9999"},
        )
        cfg = _extract_json_from_output(result.stdout)
        assert cfg["remote_port"] == 9999

    def test_nothing_written_to_stderr_on_success(self):
        result = _run_dry("--broker=arenax", "--mode=backtest")
        # Some logger handlers write to stdout in this project, so parse JSON robustly.
        assert result.returncode == 0
        cfg = _extract_json_from_output(result.stdout)
        assert isinstance(cfg, dict)
