import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from typing import Optional

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
from flask import send_from_directory
from werkzeug.serving import make_server
# from cjtrade.apps.ArenaX.arenax_account_client import *

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
    # server_config['backtest_mode'] = server_config.get('backtest_mode', 'y').lower() == 'y'
    server_config['playback_speed'] = float(server_config.get('playback_speed', 1.0))
    server_config['backtest_duration_days'] = int(server_config.get('backtest_duration_days', 365))

    # For backward compatibility ('speed' will be replaced by 'playback_speed')
    server_config['speed'] = server_config['playback_speed']
    server_config['backtest_duration'] = server_config['backtest_duration_days']
    server_config['num_days_preload'] = server_config['backtest_duration_days']


# Provide an interface for apps to:
#   start / stop
#   adjust market time / playback speed
#   flush price data cache (don't do this)
#   and all the communication are through the listening of background thread (main thread keep doing things)
# TODO: Consider about how to manage AreanX_Market (Mainly for time management) and ArenaX_Backend
#        because HTTP server starts means time starts to progress fastly but ArenaX_Backend does not
#        automatically starts which will be a bit weird when calling snapshot().
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
            # TODO: Add more backend config
            if backend_str == "hist":
                # Current default, ArenaX use sinopac backend for price feed.
                self.real = AccountClient(broker_type=BrokerType.SINOPAC, **backend_config)
                self.backend = ArenaX_Backend_Historical(real_account=self.real, **server_config)
            elif backend_str == "live":
                self.backend = ArenaX_Backend_PaperTrade(**server_config)
            elif backend_str == "none":
                self.backend = ArenaX_Backend_None(**server_config)
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
        self._valid_api_keys = set()            # Placeholder for API key management
        self._valid_api_keys.add('testkey123')  # hardcoded API key for testing

        prepare_price_db(price_db_path)
        self._app = self._create_app()

################################ HTTP Interface ##################################

    def _create_app(self) -> Flask:
        app = Flask(__name__)

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        @app.route('/favicon.ico')
        def favicon():
            return send_from_directory(
                os.path.join(BASE_DIR, 'static'),  # folder for static files
                'cj.ico',  # filename
                mimetype='image/vnd.microsoft.icon'
            )

        @app.get("/health")
        def health():
            return jsonify({
                "ok": True,
                "running": self._running,
                "backend_connected": self.backend.is_connected() if hasattr(self.backend, "is_connected") else False,
            })

        @app.post("/control/start-backend")
        def control_start():
            self.start_backend()
            return jsonify({"ok": True, "running": self._running})

        @app.post("/control/stop-backend")
        def control_stop():
            self.stop_backend()
            return jsonify({"ok": True, "running": self._running})

        # Note: for user, they only care about setting "mock current time" / "mock init time"
        # server should record the anchor time (real init time) when receiving requests.
        # User: want to backtest for another period -> set system time -> set playback speed -> start! -> backtest finished -> pause
        # there are 3 levels of stop
        #   1. Only stop time progress (mock current time would stop at a specific point)
        #   2. Kill the backend (endpoint `/control/stop` do this)
        #   3. Stop the whole server (kill the process at OS-level, there will be a systemd service file for this in the future)
        @app.post("/control/set-time")
        def control_set_time():
            payload = request.get_json(silent=True) or {}
            anchor_time = payload.get("anchor_time")
            if not anchor_time:
                return jsonify({"ok": False, "error": "anchor_time is required"}), 400
            parsed_time = datetime.fromisoformat(anchor_time)
            preloaded = self.set_system_time(parsed_time)
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
                "paused": t.get("paused", False),
                "paused_time": t["paused_time"].isoformat() if t.get("paused_time") else None,
            })

        @app.post("/control/pause-time-progress")
        def control_pause():
            if not hasattr(self.backend, "market") or not hasattr(self.backend.market, "pause_time_progress"):
                return jsonify({"ok": False, "error": "pause not supported"}), 400
            try:
                paused_time = self.backend.market.pause_time_progress()
                return jsonify({"ok": True, "paused": True, "paused_time": paused_time.isoformat()}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.post("/control/resume-time-progress")
        def control_resume():
            if not hasattr(self.backend, "market") or not hasattr(self.backend.market, "resume_time_progress"):
                return jsonify({"ok": False, "error": "resume not supported"}), 400
            try:
                baseline = self.backend.market.resume_time_progress()
                return jsonify({"ok": True, "paused": False, "baseline": baseline.isoformat()}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.get("/control/get-config")
        def control_get_config():
            return jsonify({
                "server_config": server_config,
                "backend_config": backend_config,
            })

        @app.get("/control/get-price")
        def control_get_price():
            symbol = request.args.get("symbol")
            if not symbol:
                return jsonify({"ok": False, "error": "symbol is required"}), 400
            price = self.backend.snapshot(symbol)
            return jsonify({"ok": True, "symbol": symbol, "price": str(price)})

        @app.post("/account/login")
        def login():
            payload = request.get_json(silent=True) or {}
            api_key = payload.get("api_key")
            if api_key in self._valid_api_keys:
                print(f"API key {api_key} is valid. Login successful.")
                return jsonify({"ok": True, "message": "Login successful"})
            else:
                print(f"API key {api_key} is invalid. Login failed.")
                return jsonify({"ok": False, "message": "Invalid API key"}), 401

        @app.post("/account/logout")
        def logout():
            return jsonify({"ok": True, "message": "Logout successful"})

        # Contains account balance, positions, orders
        @app.get("/account/summary")
        def account_summary():
            b = self.backend.account_balance()
            p = self.backend.list_positions()
            o = self.backend.list_trades()
            return jsonify({
                "ok": True,
                "balance": b if b is not None else None,
                "positions": p if p is not None else None,
                "orders": o if o is not None else None,
            })


        @app.post("/trade/place-order")
        def place_order():
            payload = request.get_json(silent=True) or {}
            product_payload = payload.get("product") or {}
            action = payload.get("action")
            price = payload.get("price")
            quantity = payload.get("quantity")
            price_type = payload.get("price_type")
            order_type = payload.get("order_type")
            order_lot = payload.get("order_lot")
            opt_field = payload.get("opt_field")
            id = payload.get("id")   # <-- REALLY IMPORTANT bcuz we don't want to let factory method generate a new ID
            if not all([product_payload, action, price is not None, quantity is not None, price_type, order_type, order_lot]):
                return jsonify({"ok": False, "error": "Missing required order fields"}), 400
            try:
                # Build Product from incoming dict
                product = Product(**product_payload) if isinstance(product_payload, dict) else Product(symbol=product_payload)

                # Normalize order_lot: could be string or already enum name
                try:
                    # TODO: to-check, should be OrderLot(order_lot) or order_lot directly
                    order_lot_enum = OrderLot(order_lot) if isinstance(order_lot, str) else OrderLot(order_lot)
                except Exception:
                    # Fallback: try boolean mapping
                    order_lot_enum = OrderLot.IntraDayOdd if str(order_lot).lower() in ["1", "true", "yes"] else OrderLot.Common

                order = Order(
                    product=product,
                    action=OrderAction(action),
                    price=float(price),
                    quantity=int(quantity),
                    price_type=PriceType(price_type),
                    order_type=OrderType(order_type),
                    order_lot=order_lot_enum,
                    id=id,
                    opt_field=opt_field,
                )
                result = self.backend.place_order(order)
                print(f"Placing order {order.__dict__}")
                print(f"Order result: {result.__dict__ if result else None}")
                return jsonify({"ok":True, "result": result.to_dict() if result else None}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.post("/trade/cancel-order")
        def cancel_order():
            payload = request.get_json(silent=True) or {}
            order_id = payload.get("order_id")
            if not order_id:
                return jsonify({"ok": False, "error": "order_id is required"}), 400
            try:
                result = self.backend.cancel_order(order_id)
                print(f"Cancelling order {order_id}")
                print(f"Order result: {result.__dict__ if result else None}")
                return jsonify({"ok": True, "result": result.to_dict() if result else None}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.post("/trade/commit-order")
        def commit_order():
            payload = request.get_json(silent=True) or {}
            order_id = payload.get("order_id")
            if not order_id:
                return jsonify({"ok": False, "error": "order_id is required"}), 400
            try:
                result = self.backend.commit_order(order_id)
                return jsonify({"ok": True, "result": result.to_dict() if result else None}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.get("/market/snapshot")
        def market_snapshot():
            symbol = request.args.get("symbol")
            if not symbol:
                return jsonify({"ok": False, "error": "symbol is required"}), 400
            price = self.backend.snapshot(symbol)
            # print(type(price))  # Snapshot
            # print(type(price.to_dict()))  # dict
            return jsonify({"ok": True, "symbol": symbol, "price": price.to_dict() if price else None})

        @app.get("/market/kbars")
        def market_kbars():
            symbol = request.args.get("symbol")
            start = request.args.get("start")
            end = request.args.get("end")
            interval = request.args.get("interval", "1m")
            try:
                kbars = self.backend.kbars(symbol, start, end, interval)
                return jsonify({"ok": True, "result": [kb.__dict__ for kb in kbars]}), 200
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @app.post("/trade/register-order-callback")
        def register_order_callback():
            return jsonify({"ok": False, "error": "not implemented"}), 501

        @app.get("/trade/get-broker-name")
        def trade_get_broker_name():
            return jsonify({"ok": True, "broker": self.backend.broker_name if hasattr(self.backend, "broker_name") else "unknown"})

        return app


################################ Core logic ##################################

    def start_backend(self) -> None:
        if self._running:
            return
        self.backend.login()
        self._stop_event.clear()
        self._matching_thread = threading.Thread(
            target=self._matching_loop,
            name="ArenaXMatchingLoop",
            daemon=True,
        )
        self._matching_thread.start()
        self._running = True

    def stop_backend(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._matching_thread:
            self._matching_thread.join(timeout=5)
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
        self.start_backend()      # TODO: Consider about disable auto-start (this may cause side-effect)

    def stop_http(self) -> None:
        if not self._http_server:
            return
        self._http_server.shutdown()
        self._http_server = None

    def serve_forever(self) -> None:
        self.start_http()
        if self._http_thread:
            self._http_thread.join()

    # NOTE: What if we call set_system_time when backend is not running? (haven't triggered backend.login())
    #   ANS: The system time start to progress once the `ArenaX_Backend_Historical`
    #        calls `_initialize_market_time()` in its `__init__`.
    #        and the `ArenaX_Backend_Historical` instance is created when
    #        `ArenaX_BrokerSideServer` is created, so it does not affect anything!
    #        The `backend` and `backend.market` is still accessible,
    #        `backend.login()`` (or calling `start_backend()`) only affects
    #        whether account state is synced, and all the functions in `ArenaX_BackendBase`
    #        that required `_connected` flag set.
    #
    # NOTE: What if set_system_time is called and the `auto_preload_data` is set when backend is not running?
    #   ANS: Because the price data preload process requires account info (e.g. positions),
    #        and the `real_account` is connected when the `ArenaX_BackendBase` is initialized,
    #        and then `ArenaX_Backend_Historical` passes the `real_account` to `ArenaX_Market`,
    #        so it is possible that the preload process can fetch data from real broker.
    #        However, this is only for current behavior of `ArenaX_BackendBase`, so this is not
    #        guaranteed that setting `auto_preload_data` will always work as expected.
    #
    # Only set system mock_init_time and real_init_time without side-effect
    def set_system_time(
        self,
        mock_init_time: datetime,
        real_init_time: Optional[datetime] = None,
        auto_start_progress: bool = True,
        auto_preload_data: bool = True
    ) -> list[str]:
        if real_init_time is None:
            real_init_time = datetime.now()
        self.backend.market.set_historical_time_abs(real_init_time, mock_init_time)
        if not auto_start_progress:
            self.backend.market.pause_time_progress()
        if auto_preload_data:
            self._preload_data(None, None)

    # TODO: Need to verify functionality and carify data flow (whom to consume the symbols to preload)
    # NOTE: What if in the future `start_backend()` will not be automatically called when `start_http()`,
    #       and especially when `playback_speed` is really high, and then user call `set_system_time()`
    #       with `auto_preload_data=True` but backend is not running, will the preloaded data still be
    #       available when backend is started? (Currently, when data is not enough, the `ArenaX_BackendBase`
    #       will circularly reuse the existing data, so on the surface it does not really matter, but from
    #       the backtesting point of view, it is really bad.)
    #
    # TODO: Consider about whether to:
    #       1. Reset another random system time and preload data when backend is connected on the time
    #          that all data has expired.
    #       2. ......?
    #
    # NOTE: Because this `_preload_data()` function requires caller to know which symbols to preload,
    #       but the `ArenaX_BrokerSideServer` itself only know `WATCH_LIST` from config, it does not
    #       know about what positions the account has, although by current behavior, the `real_account`
    #       is automatically connected when `ArenaX_BackendBase` is initialized, so it is possible for
    #       `server._preload_data()` to ask the backend real_account what symbols to prealod. But this
    #       data flow is a bit weird, so consider to bind the `_preload_data()` with backend life cycle,
    #       so that there won't be any ambiguity about when and who to call the `_preload_data()`.
    def _preload_data(
        self,
        preload_symbols: Optional[Iterable[str]],
        preload_days: Optional[int],
    ) -> list[str]:
        if not hasattr(self.backend, "market"):
            return []

        symbols = [symbol for symbol in (preload_symbols or []) if symbol]

        if not symbols and not self.backend.real_account:
            print("Warning: No symbols specified and cannot fetch positions from real account. Abort!")
            return []

        if not self.backend.is_connected():
            print("Warning: Calling _preload_data() when backend is not connected!")
            print("         The symbols to preload may be outdated (only when backend.login() will sync account state)")
        # NOTE: Weird data flow occurs here!
        symbols = [s.symbol for s in self.backend.real_account.get_positions()] if not symbols else symbols
        days = preload_days or getattr(self.backend, "num_days_preload", 3)

        print(f"Preloading data for symbols: {symbols} for {preload_days} days...")
        for symbol in symbols:
            self.backend.market.create_historical_market(symbol, days)
        return sorted(symbols)

    def _matching_loop(self) -> None:
        while not self._stop_event.is_set():
            if hasattr(self.backend, "_check_if_any_order_filled"):
                self.backend._check_if_any_order_filled()  # NOTE: this function has implicit print
            self._stop_event.wait(self._match_interval)
            # self._stop_event.wait(100)

def main():
    import argparse
    load_cjconf()
    load_cjsys()

    parser = argparse.ArgumentParser(description="Run the ArenaX BrokerSide Server.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server.")
    parser.add_argument("--port", type=int, default=8801, help="Port to bind the server.")
    parser.add_argument("--backend", type=str, choices=["hist", "live", "none"], default="none", help="Backend type to use.")
    args = parser.parse_args()

    server = ArenaX_BrokerSideServer(host=args.host, port=args.port, backend_str=args.backend)
    print(f"Starting server on {args.host}:{args.port} with backend '{args.backend}'...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop_http()
        server.stop_backend()

if __name__ == "__main__":
    main()
