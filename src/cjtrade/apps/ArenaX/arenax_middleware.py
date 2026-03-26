import requests


class ArenaXMiddleWare:
    def __init__(self, host: str = "localhost", port: int = 8801):
        self.host = host
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"

    def _get(self, path: str):
        url = f"{self.base_url}/{path}"
        try:
            res = requests.get(url, timeout=3)
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

            res = requests.post(url, json=data, headers=hdrs, timeout=3)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException as e:
            print(f"[ArenaX] Request failed: {e}")
            return None

    def check_health(self, **kwargs) -> bool:
        data = self._get("health")
        return data

    def get_system_time(self, **kwargs):
        return self._get("control/get-time")

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

    def set_system_time(self, mock_init_time: str, days_back: int = 5, preload_symbols: list | None = None, **kwargs):
        data = {
            "anchor_time": mock_init_time,
            "days_back": days_back,
        }
        if preload_symbols:
            data["preload_symbols"] = preload_symbols
        return self._post("control/set-time", data, headers=kwargs.get("headers"))

    def get_price_from_exchange(self, symbol: str, **kwargs):
        # server exposes GET /control/get-price?symbol=<symbol>
        return self._get(f"control/get-price?symbol={symbol}")

if __name__ == "__main__":
    import time
    a = ArenaXMiddleWare()
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
