from datetime import time as dt_time

import requests
from cjtrade.pkgs.models import *
from flask import jsonify


class ArenaXMiddleWare:
    def __init__(self, host: str = "localhost", port: int = 8801):
        self.host = host
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"

    def _get(self, path: str):
        url = f"{self.base_url}/{path}"
        try:
            res = requests.get(url, timeout=30)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException as e:
            print(f"[ArenaX] Request failed: {e}")
            return None

    def _post(self, path: str, data: dict = None, headers: dict | None = None):
        """POST helper. `headers` is an optional dict of additional headers.

        For backward compatibility callers can still embed a special `_headers` key in `data`.
        """
        url = f"{self.base_url}/{path}"
        try:
            # default headers for JSON API
            hdrs = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            # extract legacy _headers from data if present
            extra = None
            if isinstance(data, dict) and "_headers" in data:
                extra = data.pop("_headers")
            # merge headers precedence: default < extra(from data) < headers param
            if isinstance(extra, dict):
                hdrs.update(extra)
            if isinstance(headers, dict):
                hdrs.update(headers)

            res = requests.post(url, json=data, headers=hdrs, timeout=10)

            try:
                # treat it as JSON response if possible
                result = res.json()
                return result
            except ValueError:
                # if not JSON format
                res.raise_for_status()
                return None

        except requests.exceptions.RequestException as e:
            # Timeout, Connection Refused
            print(f"[ArenaX] Request failed: {e}")
            return None


    def check_health(self, **kwargs) -> bool:
        data = self._get("health")
        return data

    def get_system_time(self, **kwargs) -> dict:
        t = self._get("control/get-time")
        if t:
            return t
        else:
            print(f"Failed to get system time: {t.get('error') if t else 'No response'}")
            return None

    def is_market_open(self, **kwargs) -> bool:
        # mock_current_time is an ISO 8601 naive datetime (Asia/Taipei).
        # No timezone conversion — parse as-is.
        mct = self.get_system_time()["mock_current_time"]
        dt = datetime.fromisoformat(mct)
        return (
            dt.weekday() < 5 and
            dt_time(9, 0) <= dt.time() <= dt_time(13, 30)
        )

    def get_config(self, **kwargs):
        return self._get("control/get-config")

    def start_backend(self, **kwargs):
        return self._post("control/start-backend", headers=kwargs.get("headers"))

    def stop_backend(self, **kwargs):
        return self._post("control/stop-backend", headers=kwargs.get("headers"))

    def pause_time_progress(self, **kwargs):
        return self._post("control/pause-time-progress", headers=kwargs.get("headers"))

    def resume_time_progress(self, **kwargs):
        return self._post("control/resume-time-progress", headers=kwargs.get("headers"))

    def set_system_time(self, mock_init_time: str, real_init_time: str = None, auto_start_progress: bool = True, auto_preload_data: bool = True, **kwargs):
        data = {
            "anchor_time": mock_init_time,
            # "real_init_time": real_init_time,
            # "auto_start_progress": auto_start_progress,
            # "auto_preload_data": auto_preload_data,
        }
        return self._post("control/set-time", data, headers=kwargs.get("headers"))
        # return self._post("control/set-time", data, headers=kwargs.get("headers"))

    def get_price_from_exchange(self, symbol: str, **kwargs):
        # server exposes GET /control/get-price?symbol=<symbol>
        return self._get(f"control/get-price?symbol={symbol}")

    def login(self, api_key: str, **kwargs) -> bool:
        data = {"api_key": api_key}
        response = self._post("account/login", data, headers=kwargs.get("headers"))
        if response and response.get("ok") and response.get("message") == "Login successful":
            return True
        else:
            msg = None if response is None else response.get("message")
            raise ValueError(f"Login failed: {msg}")

    def logout(self, **kwargs):
        return self._post("account/logout", headers=kwargs.get("headers"))

    def account_summary(self, **kwargs) -> dict:
        summary = self._get("account/summary")
        if summary is None:
            return None
        else:
            res = {}
            res['balance'] = summary.get("balance")
            res['positions'] = summary.get("positions", [])
            res['orders'] = summary.get("orders", [])
            return res

    def get_backtest_state(self, session_id: str = None, **kwargs) -> dict:
        """Fetch raw backtest data from the server.

        Returns a dict with keys: initial_balance, final_balance, fill_history.
        equity_curve is NOT fetched from the server; the client (cjtrade_system)
        records it locally during the backtest run.

        Args:
            session_id: If provided, fill_history is filtered to only include
                        entries that match this session_id.  This allows clean
                        isolation when the server has been running across multiple
                        backtest sessions or manual operations.
        """
        res = self._get("account/backtest-state")
        if res and res.get("ok"):
            fill_history = res.get("fill_history", [])
            if session_id is not None:
                fill_history = [
                    f for f in fill_history
                    if f.get("session_id") == session_id
                ]
            return {
                "initial_balance": res.get("initial_balance", 0.0),
                "final_balance": res.get("final_balance", 0.0),
                "fill_history": fill_history,
            }
        return None

    def snapshot(self, symbol: str, **kwargs) -> dict:
        res = self._get(f"market/snapshot?symbol={symbol}")
        if res and res.get("ok"):
            return res.get("price")  # return Snapshot object
        else:
            print(f"Failed to get snapshot for {symbol}: {res.get('error') if res else 'No response'}")
            return None

    def get_kbars(self, symbol: str, start: str, end: str,
                  interval: str = "1m") -> list:
        """Fetch historical kbars from the ArenaX server.

        Parameters
        ----------
        symbol : str   e.g. '2330'
        start  : str   ISO date or datetime string, e.g. '2024-01-02'
        end    : str   ISO date or datetime string, e.g. '2024-06-30'
        interval : str e.g. '1m', '5m', '1d'

        Returns
        -------
        list[dict]  raw dicts with keys: timestamp, open, high, low, close, volume
        """
        res = self._get(
            f"market/kbars?symbol={symbol}&start={start}&end={end}&interval={interval}"
        )
        if res and res.get("ok"):
            return res.get("result", [])
        err = res.get("error") if res else "No response"
        print(f"Failed to get kbars for {symbol}: {err}")
        return []


    def place_order(self, order: Order, **kwargs) -> OrderResult:
        # Serialize Order to JSON-serializable payload
        product = {
            "symbol": getattr(order.product, 'symbol', None),
            "exchange": getattr(order.product, 'exchange', None),
            "type": getattr(order.product, 'type', None).value if hasattr(getattr(order.product, 'type', None), 'value') else getattr(order.product, 'type', None),
        }

        data = {
            "product": product,
            "action": order.action.value if hasattr(order.action, 'value') else order.action,
            "price": float(order.price),
            "quantity": int(order.quantity),
            "price_type": order.price_type.value if hasattr(order.price_type, 'value') else order.price_type,
            "order_type": order.order_type.value if hasattr(order.order_type, 'value') else order.order_type,
            "order_lot": order.order_lot.value if hasattr(order.order_lot, 'value') else order.order_lot,
            "created_at": order.created_at.isoformat() if hasattr(order, 'created_at') else None,
            "id": order.id,
            "opt_field": order.opt_field,
        }

        # Call server endpoint (broker-side server expects /trade/place-order)
        res = self._post("trade/place-order", data, headers=kwargs.get("headers"))

        if res is None:
            raise ConnectionError("No response from ArenaX broker-side server")
        if not res.get("ok", False):
            raise ValueError(f"Place order failed: {res.get('error')}")

        result = res.get("result")
        if result is None:
            raise ValueError("Unexpected empty result from broker server")

        # Map server result dict to local OrderResult dataclass
        status = result.get("status")
        try:
            status_enum = OrderStatus(status) if status is not None else OrderStatus.UNKNOWN
        except Exception:
            status_enum = OrderStatus.UNKNOWN

        order_result = OrderResult(
            status=status_enum,
            message=result.get("message", ""),
            metadata=result.get("metadata", {}),
            linked_order=result.get("linked_order", ""),
            id=result.get("id", result.get("order_id", order.id)),
        )
        return order_result

    def cancel_order(self, order_id: str, **kwargs) -> OrderResult:
        data = {"order_id": order_id}
        res = self._post("trade/cancel-order", data, headers=kwargs.get("headers"))

        result_data = res.get("result", {})
        # print(f"Cancel order response: {res}")
        # print(f"status: {result_data.get('status')}")

        order_result = OrderResult(
            linked_order=result_data.get("linked_order"),
            status=result_data.get("status"),
            message=result_data.get("message", ""),
            metadata=result_data.get("metadata", {}),
        )
        return order_result

    def commit_order(self, order_id: str, **kwargs) -> List[OrderResult]:
        data = {"order_id": order_id}
        res = self._post("trade/commit-order", data, headers=kwargs.get("headers"))
        if res is None:
            return None
        if not res.get("ok", False):
            raise ValueError(f"Commit order failed: {res.get('error')}")

        r = res.get("result")
        if r is None:
            return None

        order_result = OrderResult(
            status=OrderStatus(r.get("status")) if r.get("status") in [s.value for s in OrderStatus] else OrderStatus.UNKNOWN,
            message=r.get("message", ""),
            metadata=r.get("metadata", {}),
            linked_order=r.get("linked_order", r.get("order_id", "")),
            id=r.get("id", r.get("order_id", "")),
        )
        return order_result


if __name__ == "__main__":
    import time
    a = ArenaXMiddleWare()
    # test is_market_open()
    # 2021-10-01 09:30:00+08:00 in RFC 1123 format
    dt = datetime(2021, 10, 1, 9, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    iso_time = dt.isoformat()
    print(f"Testing is_market_open() with mock time {iso_time}...")
    print(a.set_system_time(iso_time))
    print(f"Market open status: {a.is_market_open()}")

    exit(0)
    print(a.start_backend())
    print(a.check_health())
    print(a.stop_backend())
    print(a.start_backend())
    print(a.get_config())
    print("pausing time progress...")
    print(a.pause_time_progress())
    print(a.get_time())
    print("sleep 5 seconds and get time again...")
    time.sleep(5)
    print(a.get_system_time())
    time.sleep(5)
    print("Try to resume time progress...")
    print(a.resume_time_progress())
    print("Wait 5 seconds and get time again...")
    time.sleep(5)
    print(a.get_time())
