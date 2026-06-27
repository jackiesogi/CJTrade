"""
SystemLauncher – single entry point for all broker / mode combinations.

Responsibilities
----------------
1. Load the user-facing ``{broker}_{mode}.cjsys`` config.
2. For ArenaX: delegate server lifecycle to ``_ArenaXServerManager``
   (kill stale process, start fresh, wait for /health).
3. Hand off execution to ``cjtrade_system_arenax.async_main()``.
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

log = logging.getLogger("cjtrade.runner")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("cjtrade.arenax_server").setLevel(logging.DEBUG)
logging.getLogger("cjtrade.system_arenax").setLevel(logging.DEBUG)

_SYSTEM_CONF_DIR = Path(__file__).parent / "configs"
SERVER_STARTUP_TIMEOUT = 60  # seconds


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
            time.sleep(0.6)
    except FileNotFoundError:
        log.warning("'lsof' not found – cannot auto-kill existing server; continuing anyway")


def _wait_for_server(host: str, port: int, timeout: int = SERVER_STARTUP_TIMEOUT) -> bool:
    """Poll /health until the ArenaX server reports ``running: true``."""
    import json
    import urllib.error
    import urllib.request

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

_SERVER_KEY_MAP = {
    "CJSYS_BACKTEST_DURATION_DAYS":  "backtest_duration_days",
    "CJSYS_BACKTEST_PLAYBACK_SPEED": "playback_speed",
    "CJSYS_SKIP_NON_TRADING_HOURS":  "skip_non_trading_hours",
    "CJSYS_STATE_FILE":              "state_file",
    "CJSYS_WATCH_LIST":              "watch_list",
    "CJSYS_REMOTE_HOST":             "host",
    "CJSYS_REMOTE_PORT":             "port",
}


def _load_user_cjsys(broker: str, mode: str) -> tuple[dict, Path]:
    """Return (dotenv dict, config Path) for ``{broker}_{mode}.cjsys``."""
    cfg_file = _SYSTEM_CONF_DIR / f"{broker}_{mode}.cjsys"
    if not cfg_file.exists():
        log.error(f"Config file not found: {cfg_file}")
        sys.exit(1)
    return dotenv_values(cfg_file), cfg_file


def _build_server_overrides(user_cfg: dict, mode: str) -> dict:
    """Extract server-relevant keys; CLI env vars beat .cjsys file values."""
    overrides = {}
    for cjsys_key, srv_key in _SERVER_KEY_MAP.items():
        val = os.environ.get(cjsys_key) or user_cfg.get(cjsys_key)
        if val is not None and str(val).strip():
            overrides[srv_key] = str(val).strip()

    if "backtest_duration_days" in overrides:
        days = int(overrides["backtest_duration_days"])
        overrides["backtest_duration_days"] = days
        overrides["backtest_duration"]      = days
        overrides["num_days_preload"]       = days

    if "playback_speed" in overrides:
        speed = float(overrides["playback_speed"])
        overrides["playback_speed"] = speed
        overrides["speed"]          = speed

    if "skip_non_trading_hours" in overrides:
        val = overrides["skip_non_trading_hours"]
        overrides["skip_non_trading_hours"] = (
            val if isinstance(val, bool)
            else str(val).strip().lower() in ("y", "yes", "true", "1")
        )

    if mode in ("paper", "real"):
        overrides.setdefault("playback_speed", 1.0)
        overrides.setdefault("speed", 1.0)
        overrides["skip_non_trading_hours"] = False

    return overrides


# ---------------------------------------------------------------------------
# _ArenaXServerManager
# ---------------------------------------------------------------------------

class _ArenaXServerManager:
    """Owns the ArenaX brokerside server for one trading session.

    Separates server lifecycle (start / stop) from the general launcher logic
    so ``SystemLauncher.run()`` stays broker-agnostic except for the single
    ``if broker == "arenax"`` guard.
    """

    def __init__(self, host: str, port: int, mode: str) -> None:
        self.host  = host
        self.port  = port
        self.mode  = mode
        self._server = None

    def start(self, srv_overrides: dict) -> None:
        """Kill stale process on the port, configure & start server, wait for ready."""
        import threading

        from cjtrade.apps.ArenaX.brokerside_server import (
            ArenaX_BrokerSideServer,
            internal_config,
            load_cjconf,
        )

        load_cjconf()
        internal_config.update(srv_overrides)

        self._server = ArenaX_BrokerSideServer(
            host=self.host,
            port=self.port,
            backend_str=self.mode,
        )
        threading.Thread(
            target=self._server.serve_forever,
            name="ArenaXServer",
            daemon=True,
        ).start()

        if not _wait_for_server(self.host, self.port):
            log.error(
                f"ArenaX server did not become ready within {SERVER_STARTUP_TIMEOUT}s"
            )
            sys.exit(1)

        log.info(f"✅ ArenaX server ready at http://{self.host}:{self.port}  (mode={self.mode})")

    def stop(self) -> None:
        """Gracefully stop the server."""
        if self._server:
            try:
                self._server.stop_http()
                self._server.stop_backend()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# SystemLauncher
# ---------------------------------------------------------------------------

class SystemLauncher:
    """
    Owns the full broker + trading-system lifecycle for one session.

    Usage::

        launcher = SystemLauncher(mode="backtest", broker="arenax")
        launcher.run()
    """

    def __init__(
        self,
        mode: str,
        broker: str = "arenax",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        self.mode   = mode
        self.broker = broker
        self.host   = host
        self.port   = port

    def run(self) -> None:
        # 1. Load user config (no env mutation)
        user_cfg, cfg_file = _load_user_cjsys(self.broker, self.mode)
        srv_overrides = _build_server_overrides(user_cfg, self.mode)

        # 2. Resolve host/port: CLI > config > default
        self.host = self.host or srv_overrides.get("host") or "127.0.0.1"
        self.port = self.port or int(srv_overrides.get("port", 8801))

        log.info(f"Loaded config: {cfg_file.name}")
        log.info(f"  mode={self.mode}  broker={self.broker}")
        log.info(f"  server.host={self.host}  server.port={self.port}")
        for k, v in srv_overrides.items():
            if k not in ("host", "port"):
                log.info(f"  server.{k} = {v}")

        # 3. Start ArenaX server (ArenaX broker only)
        mgr: Optional[_ArenaXServerManager] = None
        if self.broker == "arenax":
            if _is_port_in_use(self.host, self.port):
                log.info(f"Port {self.port} in use – killing existing server…")
                _kill_on_port(self.port)
            mgr = _ArenaXServerManager(self.host, self.port, self.mode)
            mgr.start(srv_overrides)
        else:
            log.info(f"Broker '{self.broker}': skipping ArenaX server startup")

        # 4. Hand off to the trading system
        from cjtrade.apps.cjtrade_system.cjtrade_system_arenax import (
            async_main,
            build_system_config,
        )
        sys_cfg = build_system_config(self.broker, self.mode)
        try:
            asyncio.run(async_main(cfg=sys_cfg, broker=self.broker))
        finally:
            if mgr:
                mgr.stop()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="system",
        description="CJTrade System Launcher – supports ArenaX and Sinopac brokers",
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
        help="Launch mode",
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="ArenaX server host (CLI > config > default 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="ArenaX server port (CLI > config > default 8801)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print resolved SystemConfig as JSON and exit without launching.",
    )
    args = parser.parse_args()

    if args.dry_run:
        import logging as _logging
        from cjtrade.apps.cjtrade_system.cjtrade_system_arenax import build_system_config
        prev = _logging.root.manager.disable
        _logging.disable(_logging.CRITICAL)
        try:
            cfg = build_system_config(args.broker, args.mode)
        finally:
            _logging.disable(prev)
        print(cfg.dump_json())
        sys.exit(0)

    SystemLauncher(
        mode=args.mode,
        broker=args.broker,
        host=args.host,
        port=args.port,
    ).run()


if __name__ == "__main__":
    main()
