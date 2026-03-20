import requests


class ArenaXMiddleWare:
    def __init__(self):
        self.base_url = "http://localhost:8801"

    def _get(self, path: str):
        url = f"{self.base_url}{path}"
        try:
            res = requests.get(url, timeout=3)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException as e:
            print(f"[ArenaX] Request failed: {e}")
            return None

    def check_health(self) -> bool:
        data = self._get("/health")
        return data is not None and data.get("ok", False)

    def get_time(self):
        return self._get("/control/get-time")


if __name__ == "__main__":
    a = ArenaXMiddleWare()
    print(a.check_health())
    print(a.get_time())
