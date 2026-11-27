"""Broker credentials read from SINOPAC_* / FUBON_* settings."""
import pytest
from cjtrade.pkgs.config import broker_settings as bs


@pytest.fixture(autouse=True)
def fresh_warnings():
    bs._warned.clear()


SINOPAC = {"SINOPAC_API_KEY": "k", "SINOPAC_SECRET_KEY": "s",
           "SINOPAC_CA_CERT_PATH": "/c.pfx", "SINOPAC_CA_PASSWORD": "p"}
OLD = {"API_KEY": "ok", "SECRET_KEY": "os", "CA_CERT_PATH": "/old.pfx", "CA_PASSWORD": "op"}


class TestSinopac:
    def test_prefixed_settings_become_the_constructor_arguments(self):
        assert bs.sinopac_config(SINOPAC) == {"api_key": "k", "secret_key": "s", "ca_path": "/c.pfx",
                                              "ca_passwd": "p", "simulation": False}

    def test_the_old_names_still_work_and_warn_once(self, caplog):
        assert bs.sinopac_credentials(OLD)["ca_path"] == "/old.pfx"
        bs.sinopac_credentials(OLD)
        warnings = [r for r in caplog.records if "API_KEY is deprecated" in r.getMessage()]
        assert len(warnings) == 1

    def test_a_prefixed_setting_wins_over_the_old_name(self):
        assert bs.sinopac_credentials({**OLD, **SINOPAC})["api_key"] == "k"

    @pytest.mark.parametrize("env, sandbox", [
        ({}, False),
        ({"SINOPAC_SIMULATION": "y"}, True),
        ({"SIMULATION": "yes"}, True),
        ({"SINOPAC_SIMULATION": "n", "SIMULATION": "y"}, True),
        ({"SINOPAC_SIMULATION": "y", "SIMULATION": "n"}, True),
        ({"SINOPAC_SIMULATION": "n"}, False),
    ])
    def test_any_setting_asking_for_the_sandbox_gets_it(self, env, sandbox):
        assert bs.sinopac_simulation(env) is sandbox

    def test_credentials_leave_the_sandbox_flag_to_the_adapter(self):
        assert "simulation" not in bs.sinopac_credentials(SINOPAC)

    def test_missing_settings_are_named_by_their_new_names(self):
        assert bs.sinopac_missing({"SINOPAC_API_KEY": "k", "SECRET_KEY": "s"}) == \
            ["SINOPAC_CA_CERT_PATH", "SINOPAC_CA_PASSWORD"]


class TestFubon:
    def test_set_settings_become_arguments_and_unset_ones_are_left_out(self):
        env = {"FUBON_PERSONAL_ID": "A1", "FUBON_API_KEY": "k", "FUBON_CERT_PATH": "/f.pfx",
               "FUBON_ACCOUNT": ""}
        assert bs.fubon_config(env) == {"personal_id": "A1", "api_key": "k", "cert_path": "/f.pfx"}

    def test_a_password_satisfies_the_login_requirement(self):
        assert bs.fubon_missing({"FUBON_PERSONAL_ID": "A1", "FUBON_PASSWORD": "p",
                                 "FUBON_CERT_PATH": "/f.pfx"}) == []

    def test_missing_settings_are_named(self):
        assert bs.fubon_missing({}) == ["FUBON_PERSONAL_ID", "FUBON_CERT_PATH",
                                        "FUBON_API_KEY or FUBON_PASSWORD"]
