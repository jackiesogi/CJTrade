"""Unit tests for cjtrade.pkgs.config.config_loader."""
import os
from pathlib import Path

import pytest
from cjtrade.pkgs.config.config_loader import load_supported_config_files


class TestLoadSupportedConfigFiles:
    def test_load_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_CONFIG=hello_from_test\n")

        loaded = load_supported_config_files(paths=[env_file], override=True)
        assert str(env_file) in loaded
        assert os.environ.get("TEST_VAR_CONFIG") == "hello_from_test"

        # cleanup
        os.environ.pop("TEST_VAR_CONFIG", None)

    def test_load_cjconf_from_directory(self, tmp_path):
        conf = tmp_path / "my.cjconf"
        conf.write_text("DIR_VAR=from_cjconf\n")

        loaded = load_supported_config_files(paths=[tmp_path], recursive_pattern="*.cjconf", override=True)
        assert str(conf) in loaded
        assert os.environ.get("DIR_VAR") == "from_cjconf"

        os.environ.pop("DIR_VAR", None)

    def test_load_nested_cjconf(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        conf = sub / "nested.cjconf"
        conf.write_text("NESTED_VAR=deep\n")

        loaded = load_supported_config_files(paths=[tmp_path], recursive_pattern="*.cjconf", override=True)
        assert str(conf) in loaded
        assert os.environ.get("NESTED_VAR") == "deep"

        os.environ.pop("NESTED_VAR", None)

    def test_none_paths_returns_empty(self):
        loaded = load_supported_config_files(paths=None)
        assert loaded == []

    def test_nonexistent_path_skipped(self, tmp_path):
        fake = tmp_path / "does_not_exist.env"
        loaded = load_supported_config_files(paths=[fake])
        assert loaded == []

    def test_glob_pattern_in_paths(self, tmp_path):
        f1 = tmp_path / "a.cjconf"
        f2 = tmp_path / "b.cjconf"
        f1.write_text("GLOB_A=1\n")
        f2.write_text("GLOB_B=2\n")

        pattern = str(tmp_path / "*.cjconf")
        loaded = load_supported_config_files(paths=[pattern], override=True)
        assert len(loaded) == 2
        assert os.environ.get("GLOB_A") == "1"
        assert os.environ.get("GLOB_B") == "2"

        os.environ.pop("GLOB_A", None)
        os.environ.pop("GLOB_B", None)

    def test_override_false_does_not_clobber(self, tmp_path):
        os.environ["KEEP_ME"] = "original"
        conf = tmp_path / "override.cjconf"
        conf.write_text("KEEP_ME=clobbered\n")

        load_supported_config_files(paths=[conf], override=False)
        assert os.environ["KEEP_ME"] == "original"

        os.environ.pop("KEEP_ME", None)
