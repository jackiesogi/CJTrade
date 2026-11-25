"""FinMindMarketData: TWSE/TPEx data from the FinMind open-data API.

https://finmind.github.io/ . Daily bars are free with or without a token
(more requests per hour with one). Minute bars and ticks need a sponsor
plan: until the account has one, those requests raise UnsupportedRequest
and the source stops advertising them, so a Fallback moves on.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs.marketdata.aggregate import aggregate
from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import closed
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import INTRADAY_INTERVALS
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import MarketDataUnavailable
from cjtrade.pkgs.marketdata.base import require_online
from cjtrade.pkgs.marketdata.base import session_days
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_datetime
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.marketdata.base import UnsupportedRequest
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.tick import Tick
from cjtrade.pkgs.models.tick import TickSide

log = logging.getLogger("cjtrade.marketdata.finmind")

API = "https://api.finmindtrade.com/api/v4/data"
_PLAN_HINT = "update your user level"     # FinMind's message for a plan gate


class FinMindMarketData(MarketData):
    """Bars and ticks from FinMind.

    Parameters
    ----------
    token : str, optional
        API token. Defaults to the ``FINMIND_TOKEN`` setting; works without
        one at a lower request limit.
    timeout : float, optional
        Seconds per HTTP request.

    Notes
    -----
    Datasets used: ``TaiwanStockPrice`` (1d), ``TaiwanStockKBar`` (1m, one
    request per symbol per day; 5m-1h are aggregated from it) and
    ``TaiwanStockPriceTick``. Daily volume is converted from shares to lots;
    FinMind's minute bars are stamped at their start and are shifted to
    their close.

    Warnings
    --------
    Makes network calls and counts against the account's hourly request
    limit (600 for a registered free account).
    """

    name = "finmind"

    def __init__(self, token: Optional[str] = None, timeout: float = 30.0) -> None:
        self.token = token if token is not None else os.environ.get("FINMIND_TOKEN", "")
        self.timeout = timeout
        # None: not tried yet. False: the plan does not include it.
        self._minute_ok: Optional[bool] = None
        self._ticks_ok: Optional[bool] = None

    @property
    def capabilities(self) -> Capabilities:
        intervals = {"1d"}
        if self._minute_ok is not False:
            intervals |= set(INTRADAY_INTERVALS)
        return Capabilities(intervals=frozenset(intervals),
                            ticks=self._ticks_ok is not False)

    # ── HTTP ───────────────────────────────────────────────────────────────

    def _request(self, params: Dict[str, str]) -> List[dict]:
        require_online(self.name)
        import requests
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            resp = requests.get(API, params=params, headers=headers, timeout=self.timeout)
            body = resp.json()
        except Exception as e:                           # noqa: BLE001
            raise MarketDataUnavailable(f"finmind: {e}") from e
        status = body.get("status", resp.status_code)
        if status == 200:
            return body.get("data") or []
        msg = str(body.get("msg", ""))
        if _PLAN_HINT in msg.lower():
            raise UnsupportedRequest(f"finmind: {params['dataset']} is not in this plan ({msg})")
        raise MarketDataUnavailable(f"finmind {params['dataset']}: {status} {msg}")

    # ── bars ───────────────────────────────────────────────────────────────

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        if end_dt <= start_dt:
            return []
        if interval == "1d":
            bars = self._daily(symbol, start_dt, end_dt)
        else:
            bars = aggregate(self._minutes(symbol, start_dt, end_dt), interval)
        return closed(in_window(bars, start_dt, end_dt), interval, self.now())

    def _daily(self, symbol: str, start: datetime, end: datetime) -> List[Kbar]:
        rows = self._request({
            "dataset": "TaiwanStockPrice", "data_id": symbol,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": (end - timedelta(microseconds=1)).strftime("%Y-%m-%d"),
        })
        bars = []
        for r in rows:
            day = datetime.strptime(r["date"], "%Y-%m-%d")
            bars.append(Kbar(
                timestamp=day.replace(hour=9),
                open=float(r["open"]), high=float(r["max"]),
                low=float(r["min"]), close=float(r["close"]),
                volume=int(round(float(r["Trading_Volume"]) / 1000)),
                symbol=symbol,
            ))
        return bars

    def _minutes(self, symbol: str, start: datetime, end: datetime) -> List[Kbar]:
        bars: List[Kbar] = []
        for day in session_days(start, end):
            try:
                rows = self._request({"dataset": "TaiwanStockKBar", "data_id": symbol,
                                      "start_date": day.isoformat()})
            except UnsupportedRequest:
                self._minute_ok = False
                raise
            self._minute_ok = True
            for r in rows:
                opened = datetime.strptime(f"{r['date']} {r['minute']}", "%Y-%m-%d %H:%M:%S")
                bars.append(Kbar(
                    timestamp=opened + timedelta(minutes=1),
                    open=float(r["open"]), high=float(r["high"]),
                    low=float(r["low"]), close=float(r["close"]),
                    volume=int(round(float(r["volume"]))),
                    symbol=symbol,
                ))
        return bars

    # ── ticks ──────────────────────────────────────────────────────────────

    def get_ticks(self, symbol: str, day: TimeLike) -> List[Tick]:
        if self._ticks_ok is False:
            raise UnsupportedRequest("finmind: ticks are not in this plan")
        day_dt = to_datetime(day)
        try:
            rows = self._request({"dataset": "TaiwanStockPriceTick", "data_id": symbol,
                                  "start_date": day_dt.strftime("%Y-%m-%d")})
        except UnsupportedRequest:
            self._ticks_ok = False
            raise
        self._ticks_ok = True
        side = {"1": TickSide.BUY, "2": TickSide.SELL}
        now = self.now()
        ticks = []
        for r in rows:
            stamp = datetime.strptime(f"{r['date']} {r['Time']}", "%Y-%m-%d %H:%M:%S.%f")
            if stamp > now:
                continue
            ticks.append(Tick(timestamp=stamp, price=float(r["deal_price"]),
                              volume=int(r["volume"]), symbol=symbol,
                              side=side.get(str(r.get("TickType")), TickSide.UNKNOWN)))
        return ticks

    # ── extras FinMind has and other sources may not ───────────────────────

    def trading_days(self, start: TimeLike, end: TimeLike) -> List[datetime]:
        """Sessions in ``[start, end)``, holidays excluded.

        Warnings
        --------
        Makes a network call.
        """
        start_dt, end_dt = to_window(start, end)
        rows = self._request({
            "dataset": "TaiwanStockTradingDate",
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": (end_dt - timedelta(microseconds=1)).strftime("%Y-%m-%d"),
        })
        return [datetime.strptime(r["date"], "%Y-%m-%d") for r in rows]
