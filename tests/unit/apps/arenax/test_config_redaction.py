"""Unit tests for _redact_secrets — GET /api/v1/config must not serve credentials."""
import pytest
from cjtrade.apps.ArenaX.brokerside_server import _redact_secrets
from cjtrade.apps.ArenaX.brokerside_server import _REDACTED


class TestRedactSecrets:
    def test_redacts_every_credential_shape_in_external_config(self):
        """The real external_config key set, as loaded from *.cjconf."""
        cfg = {
            "api_key": "AKIA-looking-thing",
            "secret_key": "s3cr3t",
            "ca_password": "pw",
            "ca_passwd": "pw",
            "newsapi_api_key": "nk",
            "ca_cert_path": "/Users/me/Sinopac.pfx",
            "ca_path": "/Users/me/Sinopac.pfx",
            "simulation": False,
        }
        out = _redact_secrets(cfg)
        for k in ("api_key", "secret_key", "ca_password", "ca_passwd", "newsapi_api_key"):
            assert out[k] == _REDACTED, k
        # Non-secrets survive, so the endpoint stays useful.
        assert out["simulation"] is False
        assert out["ca_cert_path"] == "/Users/me/Sinopac.pfx"

    def test_keeps_internal_config_readable(self):
        cfg = {"launch_mode": "demo", "playback_speed": 120.0, "host_port": "8801"}
        assert _redact_secrets(cfg) == cfg

    def test_matches_on_substring_so_new_keys_are_covered(self):
        out = _redact_secrets({"broker_access_token": "t", "refresh_credential": "c"})
        assert out["broker_access_token"] == _REDACTED
        assert out["refresh_credential"] == _REDACTED

    def test_is_case_insensitive(self):
        assert _redact_secrets({"API_KEY": "x"})["API_KEY"] == _REDACTED

    def test_does_not_mutate_the_input(self):
        cfg = {"api_key": "real"}
        _redact_secrets(cfg)
        assert cfg["api_key"] == "real"

    def test_tolerates_a_non_dict(self):
        assert _redact_secrets(None) is None


if __name__ == "__main__":
    pytest.main([__file__])
