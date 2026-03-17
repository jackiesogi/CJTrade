import threading
from datetime import datetime
from typing import Iterable
from typing import Optional

from cjtrade.apps.ArenaX.base_backend import ArenaX_BackendBase
from cjtrade.apps.ArenaX.hist_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.live_backend import ArenaX_Backend_PaperTrade
from cjtrade.apps.ArenaX.none_backend import ArenaX_Backend_None
from flask import Flask
from flask import jsonify
from flask import request
from werkzeug.serving import make_server


def prepare_price_db(price_db_path: Optional[str]):
    if not price_db_path:
        return
    # Placeholder for future price DB initialization
    return

def regular_sort_price_db(price_db_path: Optional[str]):
    # Placeholder for scheduled maintenance
    return

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
                self.backend = ArenaX_Backend_Historical()
            elif backend_str == "live":
                self.backend = ArenaX_Backend_PaperTrade()
            elif backend_str == "none":
                self.backend = ArenaX_Backend_None()
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


class BrokersideServer(ArenaX_BrokerSideServer):
    """Backward-compatible alias."""
