"""Broker credentials from settings, under one prefix per broker.

Usage::

    from cjtrade.pkgs.config.broker_settings import sinopac_config, fubon_config

    load_supported_config_files()               # *.cjconf -> os.environ
    client = AccountClient(BrokerType.SINOPAC, **sinopac_config())

Sinopac's keys used to be unprefixed (``API_KEY``, ``SECRET_KEY``,
``CA_CERT_PATH``, ``CA_PASSWORD``, ``SIMULATION``). They are still read when
the ``SINOPAC_`` name is unset, with a warning, so existing ``.cjconf`` files
keep working. ``API_KEY`` stays ArenaX's key name.
"""
from __future__ import annotations

import os
from typing import Mapping
from typing import Optional

from cjtrade.pkgs.logger import get_logger

log = get_logger("config")

# config argument -> (setting, deprecated setting)
SINOPAC_SETTINGS = {
    "api_key": ("SINOPAC_API_KEY", "API_KEY"),
    "secret_key": ("SINOPAC_SECRET_KEY", "SECRET_KEY"),
    "ca_path": ("SINOPAC_CA_CERT_PATH", "CA_CERT_PATH"),
    "ca_passwd": ("SINOPAC_CA_PASSWORD", "CA_PASSWORD"),
}
SINOPAC_SIMULATION = ("SINOPAC_SIMULATION", "SIMULATION")

FUBON_SETTINGS = {
    "personal_id": "FUBON_PERSONAL_ID",
    "api_key": "FUBON_API_KEY",
    "password": "FUBON_PASSWORD",
    "cert_path": "FUBON_CERT_PATH",
    "cert_pass": "FUBON_CERT_PASSWORD",
    "account": "FUBON_ACCOUNT",
}

_warned: set[str] = set()


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def setting(name: str, old: Optional[str] = None,
            env: Optional[Mapping[str, str]] = None) -> str:
    """The value of `name`, else of the deprecated `old` (warning once), else ``""``."""
    env = _env(env)
    if env.get(name):
        return env[name]
    if old and env.get(old):
        if old not in _warned:
            _warned.add(old)
            log.warning("%s is deprecated; rename it to %s", old, name)
        return env[old]
    return ""


def _yes(value: str) -> bool:
    return str(value or "").strip().lower() in ("y", "yes", "true", "1")


def sinopac_simulation(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether to use Sinopac's sandbox.

    True when either ``SINOPAC_SIMULATION`` or the deprecated ``SIMULATION``
    says yes, so a setting that asks for the sandbox is never overridden by
    one that does not. CI relies on this.
    """
    env = _env(env)
    return any(_yes(env.get(k, "")) for k in SINOPAC_SIMULATION)


def sinopac_credentials(env: Optional[Mapping[str, str]] = None) -> dict:
    """The key, secret and certificate arguments, without ``simulation``.

    For callers that leave the sandbox flag to SinopacBrokerAPI's default (True).
    """
    return {arg: setting(new, old, env) for arg, (new, old) in SINOPAC_SETTINGS.items()}


def sinopac_config(env: Optional[Mapping[str, str]] = None) -> dict:
    """``AccountClient(BrokerType.SINOPAC, **...)`` arguments from settings.

    ``simulation`` follows the settings: False (the real account) unless one
    of them asks for the sandbox.
    """
    config = sinopac_credentials(env)
    config["simulation"] = sinopac_simulation(env)
    return config


def sinopac_missing(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """The ``SINOPAC_*`` settings that are needed and unset (old names count)."""
    return [new for new, old in SINOPAC_SETTINGS.values() if not setting(new, old, env)]


def fubon_config(env: Optional[Mapping[str, str]] = None) -> dict:
    """``AccountClient(BrokerType.FUBON, **...)`` arguments from ``FUBON_*`` settings.

    Unset optional settings are left out, so the adapter's defaults apply.
    """
    env = _env(env)
    return {arg: env[name] for arg, name in FUBON_SETTINGS.items() if env.get(name)}


def fubon_missing(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """The ``FUBON_*`` settings that are needed and unset."""
    env = _env(env)
    missing = [n for n in ("FUBON_PERSONAL_ID", "FUBON_CERT_PATH") if not env.get(n)]
    if not (env.get("FUBON_API_KEY") or env.get("FUBON_PASSWORD")):
        missing.append("FUBON_API_KEY or FUBON_PASSWORD")
    return missing
