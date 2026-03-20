import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from typing import Optional

from cjtrade.apps.ArenaX.arenax_account_client import *
from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.hist_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.live_backend import ArenaX_Backend_PaperTrade
from cjtrade.apps.ArenaX.none_backend import ArenaX_Backend_None
from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from dotenv import load_dotenv
from flask import Flask
from flask import jsonify
from flask import request
from werkzeug.serving import make_server

backend_config = {}
server_config = {}

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("cjtrade.arenax_server")

def prepare_price_db(price_db_path: Optional[str]):
    if not price_db_path:
        return
    # Placeholder for future price DB initialization
    return

def regular_sort_price_db(price_db_path: Optional[str]):
    # Placeholder for scheduled maintenance
    return

# CJCONF is for the brokers / services configuration (e.g. API keys, certs, etc.)
def load_cjconf():
    load_supported_config_files()
    keys = ['API_KEY', 'SECRET_KEY', 'CA_CERT_PATH', 'CA_PASSWORD', 'SIMULATION',
            'USERNAME', 'LLM_API_KEY', 'LLM_MODEL', 'GEMINI_API_KEY', 'NEWSAPI_API_KEY']
    for key in keys:
        if os.environ.get(key):
            backend_config[key.lower()] = os.environ[key]

    backend_config['simulation'] = backend_config.get('simulation', 'y').lower() == 'y'
    backend_config['ca_path'] = backend_config.get('ca_cert_path', "")
    backend_config['ca_passwd'] = backend_config.get('ca_password', "")

# CJSYS is for CJTrade System itself
def load_cjsys():
    file_path = None

    if file_path:
        file_to_load = file_path
    else:
        file_to_load = Path(__file__).parent / "configs" / "arenax-server_default.cjsys"

    log.info(f"Loading config file {file_to_load}")

    load_dotenv(file_to_load, override=False)
    keys = ['BACKTEST_MODE', 'BACKTEST_DURATION', 'BACKTEST_DURATION_DAYS', 'PLAYBACK_SPEED', 'WATCH_LIST',
            'PRICE_MONITOR_INTERVAL', 'ANALYSIS_INTERVAL', 'LLM_REPORT_INTERVAL', 'DISPLAY_TIME_INTERVAL', 'CHECK_FILL_INTERVAL',
            'WINDOW_SIZE', 'BB_MIN_WIDTH_PCT',
            'RISK_MAX_POSITION_PCT']
    for key in keys:
        if os.environ.get(key):
            log.info(f"  {key}={os.environ[key]}")
            server_config[key.lower()] = os.environ[key]

    # Adjust the types of certain keys
    server_config['backtest_mode'] = server_config.get('backtest_mode', 'y').lower() == 'y'
    server_config['playback_speed'] = float(server_config.get('playback_speed', 1.0))
    server_config['backtest_duration_days'] = int(server_config.get('backtest_duration_days', 365))
    server_config['watch_list'] = server_config.get('watch_list', "").split(',') if server_config.get('watch_list') else []
    server_config['price_monitor_interval'] = float(server_config.get('price_monitor_interval', 60))
    server_config['analysis_interval'] = float(server_config.get('analysis_interval', 30))
    server_config['llm_report_interval'] = float(server_config.get('llm_report_interval', 300))
    server_config['display_time_interval'] = float(server_config.get('display_time_interval', 40))
    server_config['check_fill_interval'] = float(server_config.get('check_fill_interval', 60))
    server_config['window_size'] = int(server_config.get('window_size', 10))
    server_config['bb_min_width_pct'] = float(server_config.get('bb_min_width_pct', 0.01))
    server_config['risk_max_position_pct'] = float(server_config.get('risk_max_position_pct', 0.05))

    # For backward compatibility ('speed' will be replaced by 'playback_speed')
    server_config['speed'] = server_config['playback_speed']
    server_config['backtest_duration'] = server_config['backtest_duration_days']


# Provide an interface for apps to:
#   start / stop
#   adjust market time / playback speed
#   flush price data cache (don't do this)
#   and all the communication are through the listening of background thread (main thread keep doing things)
class ArenaX_BrokerSideServer:
    """Minimal broker-side server with REST control endpoints."""

    def __init__(
        self,
        price_db_path: Optional[str] = None,
        backend_str: str = "hist",
        backend: Optional[ArenaX_BackendBase] = None,
        host: str = "127.0.0.1",
        port: int = 8801,
        match_interval: float = 1.0,
    ):
        if backend is not None:
            self.backend = backend
        else:
            if backend_str == "hist":
                # TODO: actually it is kind of weird bcuz the backend still needs
                #       an `AccountClient` instance to fetch historical data, and
                #       it is kina like a user-end code or frontend code.
                self.real = ArenaX_AccountClient(broker_type=ArenaX_BrokerType.SINOPAC, **backend_config)
                self.client = ArenaX_AccountClient(broker_type=ArenaX_BrokerType.ARENAX, real_account=self.real, **backend_config)
                self.backend = ArenaX_Backend_Historical(real_account=self.client, **server_config)
            elif backend_str == "live":
                self.backend = ArenaX_Backend_PaperTrade(**backend_config)
            elif backend_str == "none":
                self.backend = ArenaX_Backend_None(**backend_config)
            else:
                raise ValueError(f"Unsupported backend_str: {backend_str}")

        self.host = host
        self.port = port
        self._match_interval = match_interval
        self._stop_event = threading.Event()
        self._matching_thread: Optional[threading.Thread] = None
        self._http_server = None
        self._http_thread: Optional[threading.Thread] = None
        self._running = False

        prepare_price_db(price_db_path)
        self._app = self._create_app()

    def _create_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/health")
        def health():
            return jsonify({
                "ok": True,
                "running": self._running,
                "backend_connected": self.backend.is_connected() if hasattr(self.backend, "is_connected") else False,
            })

        @app.post("/control/start")
        def control_start():
            self.start()
            return jsonify({"ok": True, "running": self._running})

        @app.post("/control/stop")
        def control_stop():
            self.stop()
            return jsonify({"ok": True, "running": self._running})

        @app.post("/control/set-time")
        def control_set_time():
            payload = request.get_json(silent=True) or {}
            anchor_time = payload.get("anchor_time")
            if not anchor_time:
                return jsonify({"ok": False, "error": "anchor_time is required"}), 400

            days_back = payload.get("days_back")
            preload_days = payload.get("preload_days")
            preload_symbols = payload.get("preload_symbols")
            parsed_time = datetime.fromisoformat(anchor_time)
            preloaded = self.set_system_time(
                parsed_time,
                days_back=days_back,
                preload_symbols=preload_symbols,
                preload_days=preload_days,
            )
            return jsonify({"ok": True, "preloaded_symbols": preloaded})

        @app.get("/control/get-time")
        def control_get_time():
            t = self.backend.market.get_market_time()
            return jsonify({
                "real_init_time": t["real_init_time"],
                "real_current_time": t["real_current_time"],
                "mock_init_time": t["mock_init_time"],
                "mock_current_time": t["mock_current_time"],
                "playback_speed": t["playback_speed"],
            })

        @app.get("/control/get-config")
        def control_get_config():
            return jsonify({
                "server_config": server_config,
                "backend_config": backend_config,
            })

        return app

    def start(self) -> None:
        if self._running:
            return
        if hasattr(self.backend, "login"):
            self.backend.login()
        self._stop_event.clear()
        self._matching_thread = threading.Thread(
            target=self._matching_loop,
            name="ArenaXMatchingLoop",
            daemon=True,
        )
        self._matching_thread.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._matching_thread:
            self._matching_thread.join(timeout=5)
        if hasattr(self.backend, "logout"):
            self.backend.logout()
        self._running = False

    def start_http(self) -> None:
        if self._http_server:
            return
        self._http_server = make_server(self.host, self.port, self._app)
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            name="ArenaXHttpServer",
            daemon=True,
        )
        self._http_thread.start()

    def stop_http(self) -> None:
        if not self._http_server:
            return
        self._http_server.shutdown()
        self._http_server = None

    def serve_forever(self) -> None:
        self.start_http()
        if self._http_thread:
            self._http_thread.join()

    def set_system_time(
        self,
        anchor_time: datetime,
        days_back: Optional[int] = None,
        preload_symbols: Optional[Iterable[str]] = None,
        preload_days: Optional[int] = None,
    ) -> list[str]:
        if not hasattr(self.backend, "market"):
            self.backend.system_time_anchor = anchor_time
            return []

        if days_back is None:
            days_back = getattr(self.backend, "num_days_preload", 3)

        self.backend.market.set_historical_time(anchor_time, days_back=days_back)
        return self._preload_data(preload_symbols, preload_days)

    def _preload_data(
        self,
        preload_symbols: Optional[Iterable[str]],
        preload_days: Optional[int],
    ) -> list[str]:
        if not hasattr(self.backend, "market"):
            return []
        symbols = [symbol for symbol in (preload_symbols or []) if symbol]
        if not symbols:
            return []
        days = preload_days or getattr(self.backend, "num_days_preload", 3)
        for symbol in symbols:
            self.backend.market.create_historical_market(symbol, days)
        return sorted(symbols)

    def _matching_loop(self) -> None:
        while not self._stop_event.is_set():
            if hasattr(self.backend, "_check_if_any_order_filled"):
                self.backend._check_if_any_order_filled()
            self._stop_event.wait(self._match_interval)

if __name__ == "__main__":
    import argparse
    load_cjconf()
    load_cjsys()

    parser = argparse.ArgumentParser(description="Run the ArenaX BrokerSide Server.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server.")
    parser.add_argument("--port", type=int, default=8801, help="Port to bind the server.")
    parser.add_argument("--backend", type=str, choices=["hist", "live", "none"], default="hist", help="Backend type to use.")
    args = parser.parse_args()

    server = ArenaX_BrokerSideServer(host=args.host, port=args.port, backend_str=args.backend)
    print(f"Starting server on {args.host}:{args.port} with backend '{args.backend}'...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop_http()
        server.stop()
