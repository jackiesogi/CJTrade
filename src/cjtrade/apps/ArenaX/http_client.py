"""Minimal HTTP client for ArenaX broker-side server."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from typing import Optional
from urllib.request import Request
from urllib.request import urlopen


@dataclass
class ArenaXHttpClient:
    base_url: str = "http://127.0.0.1:8801"

    def _post(self, path: str, payload: Optional[dict] = None) -> dict:
        data = json.dumps(payload or {}).encode("utf-8")
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def start(self) -> dict:
        return self._post("/control/start")

    def stop(self) -> dict:
        return self._post("/control/stop")

    def set_system_time(
        self,
        anchor_time: datetime,
        days_back: Optional[int] = None,
        preload_days: Optional[int] = None,
        preload_symbols: Optional[Iterable[str]] = None,
    ) -> dict:
        payload = {
            "anchor_time": anchor_time.isoformat(),
            "days_back": days_back,
            "preload_days": preload_days,
            "preload_symbols": list(preload_symbols) if preload_symbols else None,
        }
        return self._post("/control/set-time", payload)
