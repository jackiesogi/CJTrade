"""Settings for FinHub.

The hosts here are where FinHub connects to the CJTrade engine and the ArenaX
broker, both loopback by default because that is where they listen. They are
not where FinHub listens: `finhub` always binds 127.0.0.1.
"""
import secrets
import sys
from pathlib import Path

from cjtrade.pkgs import paths
from cjtrade.pkgs.logger import get_logger
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

log = get_logger("FinHub.config")


class Settings(BaseSettings):
    # FINHUB_ on every variable: unprefixed SECRET_KEY and ARENAX_PORT are
    # already cjtrade names (the Sinopac secret, the engine's broker port),
    # and FinHub shares their environment.
    model_config = SettingsConfigDict(env_prefix="FINHUB_", env_file=str(paths.config_dir() / "finhub.env"),
                                      extra="ignore")

    # ── Auth ──────────────────────────────────────────────────────────────────
    # No fixed default. This key signs session tokens, and the old
    # "temporary_default_key" meant a deployment that forgot to set it ran
    # happily while anyone who had read this file could mint a token for any
    # user. Empty here and filled in below with a random value per process:
    # unset now costs you your sessions on restart, not your account.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ── Storage ───────────────────────────────────────────────────────────────
    DATABASE_URL: str = ""          # blank -> <data dir>/finhub/finhub.db

    # ── CJTrade ───────────────────────────────────────────────────────────────
    # The engine's read-only status API (apps/CJTrade/status_api.py).
    ENGINE_STATUS_HOST: str = "127.0.0.1"
    ENGINE_STATUS_PORT: int = 8898
    # The ArenaX broker-side server a run uses. 8802 is the backtest
    # instance; the supervisor hands the same port to the engine.
    ARENAX_HOST: str = "127.0.0.1"
    ARENAX_PORT: int = 8802
    ARENAX_API_KEY: str = "testkey123"
    # The interpreter that runs the broker, the engine and strategy-tool: this
    # one, so they are the cjtrade FinHub was installed with.
    PYTHON: str = sys.executable
    # Where a run's captured stdout/stderr goes.
    RUN_LOG_DIR: Path = paths.data_dir() / "finhub" / "run_logs"

    @property
    def engine_base_url(self) -> str:
        return f"http://{self.ENGINE_STATUS_HOST}:{self.ENGINE_STATUS_PORT}"

    @property
    def arenax_base_url(self) -> str:
        return f"http://{self.ARENAX_HOST}:{self.ARENAX_PORT}"


settings = Settings()

if settings.DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy dropped the bare "postgres://" scheme.
    settings.DATABASE_URL = settings.DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not settings.SECRET_KEY:
    settings.SECRET_KEY = secrets.token_urlsafe(48)
    log.warning(
        "SECRET_KEY is not set, so a random one was generated for this process. "
        "Tokens will stop working when FinHub restarts. To keep sessions across "
        "restarts put a value in %s:\n"
        "    python -c 'import secrets; print(f\"FINHUB_SECRET_KEY={secrets.token_urlsafe(48)}\")' >> %s",
        settings.model_config["env_file"], settings.model_config["env_file"]
    )

settings.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
