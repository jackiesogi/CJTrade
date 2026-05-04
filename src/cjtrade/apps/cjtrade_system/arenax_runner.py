"""
ArenaXRunner – single entry point for all ArenaX-backed trading modes.

Responsibilities
----------------
1. Load the user-facing ``{broker}_{mode}.cjsys`` config (from cjtrade_system/configs/).
2. Kill any existing ArenaX server on the target port, then start a fresh one
   with settings derived from that config file.
3. Delegate the rest of execution to ``cjtrade_system_arenax.async_main()``.

This means ``cjtrade_system_arenax`` never needs to touch the server lifecycle –
it simply trusts that the server is ready when it tries to connect.
"""
import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from dotenv import load_dotenv

log = logging.getLogger("cjtrade.runner")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s",
)
# Suppress server-side noise when running via this entry point;
# only cjtrade system logs are shown (WARNING+ from server-side is still visible).
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("cjtrade.arenax_server").setLevel(logging.DEBUG)
# logging.getLogger("cjtrade.arenax_server").setLevel(logging.WARNING)
logging.getLogger("cjtrade.system_arenax").setLevel(logging.DEBUG)

# ---- Path constants -------------------------------------------------------
# _RUNNERS_DIR     = Path(__file__).parent
# _SRC_DIR         = _RUNNERS_DIR.parent                           # src/cjtrade/
_ARENAX_DIR     = Path(__file__).parent
_SYSTEM_CONF_DIR = _ARENAX_DIR / "configs"

SERVER_STARTUP_TIMEOUT = 60   # seconds to wait for HTTP health-check


# ---------------------------------------------------------------------------
# Port utilities
# ---------------------------------------------------------------------------

def _is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _kill_on_port(port: int) -> None:
    """Send SIGKILL to every process listening on *port* (macOS / Linux)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True,
        )
        pids = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
                log.info(f"Killed existing server process PID={pid} on port {port}")
            except ProcessLookupError:
                pass
        if pids:
            time.sleep(0.6)   # give OS time to release the port
    except FileNotFoundError:
        log.warning("'lsof' not found – cannot auto-kill existing server; continuing anyway")


def _wait_for_server(host: str, port: int, timeout: int = SERVER_STARTUP_TIMEOUT) -> bool:
    """Wait until the ArenaX server is *fully* ready (backend login completed).

    We poll /health instead of just checking the TCP port.  The /health endpoint
    returns ``running: true`` only after ``start_backend()`` (including login() and
    the initial price-data sync) has finished.  This prevents the race condition
    where the system client starts making REST calls while the server is still
    writing to the price DB during login().
    """
    import urllib.request
    import urllib.error
    import json

    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                data = json.loads(resp.read())
                if data.get("running") is True:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# Config loading helpers
# ---------------------------------------------------------------------------

# Keys in the user-facing cjsys that the runner needs to translate into
# ArenaX server (internal_config) settings.
_SERVER_KEY_MAP = {
    # cjsys key                    → internal_config key
    "CJSYS_BACKTEST_DURATION_DAYS":   "backtest_duration_days",
    "CJSYS_BACKTEST_PLAYBACK_SPEED":  "playback_speed",
    "CJSYS_SKIP_NON_TRADING_HOURS":   "skip_non_trading_hours",
    "CJSYS_STATE_FILE":               "state_file",
    "CJSYS_WATCH_LIST":               "watch_list",
    "CJSYS_REMOTE_HOST":              "host",
    "CJSYS_REMOTE_PORT":              "port",
}


def _load_user_cjsys(broker: str, mode: str) -> dict:
    """Return the full dotenv dict from ``{broker}_{mode}.cjsys`` (no side-effects)."""
    cfg_file = _SYSTEM_CONF_DIR / f"{broker}_{mode}.cjsys"
    if not cfg_file.exists():
        log.error(f"Config file not found: {cfg_file}")
        sys.exit(1)
    return dotenv_values(cfg_file), cfg_file


def _build_server_overrides(user_cfg: dict, mode: str) -> dict:
    """Extract server-relevant keys from the user config dict.

    CLI-set environment variables (os.environ) take precedence over values
    from the .cjsys config file.
    """
    overrides = {}
    for cjsys_key, srv_key in _SERVER_KEY_MAP.items():
        # CLI env vars win; fall back to the .cjsys file value
        val = os.environ.get(cjsys_key) or user_cfg.get(cjsys_key)
        if val is not None and str(val).strip():
            overrides[srv_key] = str(val).strip()

    # Type coercions
    if "backtest_duration_days" in overrides:
        days = int(overrides["backtest_duration_days"])
        overrides["backtest_duration_days"]  = days
        overrides["backtest_duration"]       = days   # backward-compat alias
        overrides["num_days_preload"]        = days   # backward-compat alias

    if "playback_speed" in overrides:
        speed = float(overrides["playback_speed"])
        overrides["playback_speed"] = speed
        overrides["speed"]          = speed           # backward-compat alias

    # paper mode always real-time, never skip non-trading hours
    if mode == "paper":
        overrides.setdefault("playback_speed", 1.0)
        overrides.setdefault("speed",          1.0)
        overrides["skip_non_trading_hours"] = False   # At this point, backend has already
                                                      # parse 'n'/'y' to False/True, so we
                                                      # need to set it to a boolean value.

    return overrides


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class ArenaXRunner:
    """
    Owns the full ArenaX + cjtrade_system lifecycle for a single trading session.

    Usage::

        runner = ArenaXRunner(mode="backtest", broker="arenax")
        runner.run()
    """

    def __init__(
        self,
        mode: str,
        broker: str = "arenax",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.mode   = mode
        self.broker = broker
        self.host   = host
        self.port   = port
        self._server = None
        self._config_file = None  # Will be set in run()

    # ------------------------------------------------------------------
    def run(self) -> None:
        # 1. Load user cjsys (no env mutation yet)
        user_cfg, cfg_file = _load_user_cjsys(self.broker, self.mode)
        self._config_file = cfg_file
        srv_overrides = _build_server_overrides(user_cfg, self.mode)

        # 2. Priority for host/port: CLI > config > hardcoded default
        self.host = self.host or srv_overrides.get("host") or "127.0.0.1"
        self.port = self.port or int(srv_overrides.get("port", 8801))

        log.info(f"Loaded config: {cfg_file.name}")
        log.info(f"  mode={self.mode}  broker={self.broker}")
        log.info(f"  server.host = {self.host}")
        log.info(f"  server.port = {self.port}")
        for k, v in srv_overrides.items():
            if k not in ("host", "port"):
                log.info(f"  server.{k} = {v}")

        # 3. Kill stale server → start fresh
        if _is_port_in_use(self.host, self.port):
            log.info(f"Port {self.port} in use – killing existing server…")
            _kill_on_port(self.port)

        self._start_server(srv_overrides)

        # 4. Expose env vars for cjtrade_system_arenax.async_main()
        os.environ["BROKER_TYPE"] = self.broker
        os.environ["LAUNCH_MODE"] = self.mode
        #   Load the cjsys file into env (override=False so explicit CLI vars win)
        load_dotenv(cfg_file, override=False)

        # 5. Hand off to the trading system
        from cjtrade.apps.cjtrade_system.cjtrade_system_arenax import async_main
        try:
            asyncio.run(async_main())
        finally:
            self._stop_server()

    # ------------------------------------------------------------------
    def _start_server(self, srv_overrides: dict) -> None:
        import threading

        # Import the module-level config dicts from brokerside_server
        from cjtrade.apps.ArenaX.brokerside_server import (
            ArenaX_BrokerSideServer,
            external_config,
            internal_config,
            load_cjconf,
        )

        # Populate external_config (API keys, certs, …)
        load_cjconf()

        # Merge user-derived server settings into internal_config
        internal_config.update(srv_overrides)
        # print(f"try to override internal_config with... {srv_overrides}")
        # print(f"internal_config after override: {internal_config}")
        # print(internal_config["skip_non_trading_hours"])
        # print(internal_config)
        # time.sleep(30)

        # Create server (reads internal_config / external_config at construction time)
        self._server = ArenaX_BrokerSideServer(
            host=self.host,
            port=self.port,
            backend_str=self.mode,
        )

        t = threading.Thread(
            target=self._server.serve_forever,
            name="ArenaXServer",
            daemon=True,
        )
        t.start()

        if not _wait_for_server(self.host, self.port):
            log.error(f"ArenaX server did not become ready within {SERVER_STARTUP_TIMEOUT}s")
            sys.exit(1)

        log.info(f"✅ ArenaX server ready at http://{self.host}:{self.port}  (mode={self.mode})")

    def _stop_server(self) -> None:
        if self._server:
            try:
                self._server.stop_http()
                self._server.stop_backend()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="system",
        description="CJTrade System Launcher  –  starts ArenaX server and trading system",
    )
    parser.add_argument(
        "-B", "--broker",
        type=str, default="arenax",
        choices=["arenax", "sinopac"],
        help="Broker type (default: arenax)",
    )
    parser.add_argument(
        "-m", "--mode",
        type=str, default="backtest",
        choices=["backtest", "paper", "demo", "real"],
        help="Launch mode: backtest (backtest w/ real prices), demo (yfinance mock), paper (paper trading)",
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="ArenaX server host (CLI > config > default 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="ArenaX server port (CLI > config > default 8801)",
    )
    args = parser.parse_args()

    runner = ArenaXRunner(
        mode=args.mode,
        broker=args.broker,
        host=args.host,
        port=args.port,
    )
    runner.run()


if __name__ == "__main__":
    main()
