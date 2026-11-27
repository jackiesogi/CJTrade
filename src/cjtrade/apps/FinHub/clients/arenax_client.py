"""Client for the ArenaX broker-side REST API.

This is the shell's capability surface, reachable from a web page. Each method
below is the thing one `cjtrade` shell command does, and the mapping is
written down in the README so the two cannot quietly drift.

Why speak HTTP rather than import `cjtrade.pkgs.brokers.AccountClient`:
FinHub is a separate project with its own environment, and importing CJTrade
would drag pandas, matplotlib, quantstats and shioaji into a web server for
the sake of four endpoints. The server's REST contract is the narrow waist
that already exists.

What this deliberately copies from `ArenaXBrokerAPI_v2.buy_stock` rather than
inventing: the order fields. A limit ROD order on TSE, `IntraDayOdd` when the
caller asks for odd lots and `Common` otherwise, with the caller's own order
id so both sides can talk about the same order afterwards. Inventing a
different default here would make a manual order behave unlike an identical
one from the shell.
"""
import uuid
from datetime import datetime
from typing import Any
from typing import Optional

import httpx
from cjtrade.pkgs.logger import get_logger

from ._segments import ORDER_ID
from ._segments import segment
from ._segments import SYMBOL

log = get_logger("FinHub.arenax")

# Order field values, copied from cjtrade.pkgs.models. Spelled out rather than
# imported, and asserted against the server's own enums by the client tests.
# Note PRODUCT_TYPE is "Stocks", not "STOCK" -- that is ProductType.STOCK's
# *value*, and sending the name instead gets the order rejected.
PRODUCT_TYPE = "Stocks"
EXCHANGE = "TSE"
PRICE_TYPE_LIMIT = "LMT"
ORDER_TYPE_ROD = "ROD"
LOT_ODD = "IntraDayOdd"
LOT_COMMON = "Common"

# Which statuses the broker will still accept a cancel for. Same list the
# shell's `cancel` command uses; anything else is already resolved.
CANCELLABLE = frozenset({
    "PLACED", "COMMITTED_WAIT_MARKET_OPEN", "COMMITTED_WAIT_MATCHING",
    "PARTIAL", "PreSubmitted", "Submitted", "PartFilled",
})


class BrokerError(RuntimeError):
    """The broker refused, or could not be reached."""


class ArenaXClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # Generous: a snapshot can land while the server is preloading a month
        # of 1m bars, and the server answers 503 rather than hanging, but a
        # kbars call over a long range genuinely takes seconds.
        self.timeout = timeout

    # ── plumbing ──────────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str,
                       json: Optional[dict] = None,
                       params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(method, url, json=json, params=params)
        except httpx.RequestError as exc:
            raise BrokerError(f"broker unreachable at {url}: {exc}") from exc

        if resp.status_code == 503:
            # The server's own readiness gate: backend still warming up.
            raise BrokerError("broker is still initialising — try again shortly")
        try:
            body = resp.json()
        except ValueError as exc:
            raise BrokerError(f"{url}: non-JSON reply (HTTP {resp.status_code})") from exc

        if resp.status_code >= 400 or (isinstance(body, dict) and body.get("ok") is False):
            detail = body.get("error") or body.get("message") if isinstance(body, dict) else None
            raise BrokerError(detail or f"{url}: HTTP {resp.status_code}")
        return body

    # ── health and session ────────────────────────────────────────────────────

    async def health(self) -> dict:
        """Liveness plus two readiness flags. Answered even while warming up.

        `running` is the simulated backend; `data_readiness` is the price-cache
        preload. Polled by RunSupervisor to decide the server is usable.
        """
        return await self._request("GET", "/health")

    async def is_up(self) -> bool:
        try:
            await self.health()
            return True
        except BrokerError:
            return False

    async def login(self) -> bool:
        """Validate the API key.

        Worth knowing what this does and does not buy: the server checks the
        key here and then enforces nothing per route. So this confirms FinHub
        is pointed at a server that expects this key; it is not what protects
        the account. The loopback bind is.
        """
        body = await self._request("POST", "/api/v1/session",
                                   json={"api_key": self.api_key})
        return bool(body.get("ok"))

    async def config(self) -> dict:
        """The server's resolved config, secrets withheld by the server."""
        return await self._request("GET", "/api/v1/config")

    # ── account  (shell: balance, lspos, lsodr) ───────────────────────────────

    async def account(self) -> dict:
        """Balance, positions and orders from one read.

        One call rather than three because they come back from the same
        instant; fetching them separately gives views a round-trip apart.
        """
        body = await self._request("GET", "/api/v1/account")
        return {
            "balance": body.get("balance"),
            "positions": body.get("positions") or [],
            "orders": body.get("orders") or [],
        }

    async def orders(self) -> list:
        """Just the orders — skips re-pricing every position."""
        body = await self._request("GET", "/api/v1/orders")
        return body.get("orders") or []

    async def fills(self, session_id: Optional[str] = None) -> dict:
        """Fill history, with commission and tax the broker applied.

        These numbers exist only here: the engine never sees the cost model, so
        its own order reports have no commission on them.
        """
        body = await self._request("GET", "/api/v1/account/fills")
        history = body.get("fill_history") or []
        if session_id is not None:
            history = [f for f in history if f.get("session_id") == session_id]
        return {
            "initial_balance": body.get("initial_balance", 0.0),
            "final_balance": body.get("final_balance", 0.0),
            "fill_history": history,
        }

    # ── orders  (shell: buy, sell, cancel) ────────────────────────────────────

    def build_order(self, symbol: str, action: str, quantity: int, price: float,
                    odd_lot: bool = True, opt_field: Optional[dict] = None) -> dict:
        """The wire payload for one order. Separate from `place_order` so a
        caller can see exactly what will be sent before sending it."""
        return {
            "id": uuid.uuid4().hex,
            "product": {"symbol": symbol, "type": PRODUCT_TYPE, "exchange": EXCHANGE},
            "action": action,
            "price": float(price),
            "quantity": int(quantity),
            "price_type": PRICE_TYPE_LIMIT,
            "order_type": ORDER_TYPE_ROD,
            "order_lot": LOT_ODD if odd_lot else LOT_COMMON,
            # The server parses this, so it cannot be omitted. Wall clock, not
            # the simulated clock: the broker overwrites it with its own market
            # time on arrival, the same way ArenaXBrokerAPI_v2.place_order does.
            "created_at": datetime.now().isoformat(),
            "opt_field": opt_field or {},
        }

    async def place_order(self, symbol: str, action: str, quantity: int,
                          price: float, odd_lot: bool = True,
                          opt_field: Optional[dict] = None) -> dict:
        """Place one order and return the broker's verdict.

        The broker does the real checking — positive price and quantity,
        trading limit, sufficient balance for a buy, sufficient inventory for
        a sell — and a refusal comes back as a REJECTED status with a reason,
        not an exception. So a caller must read `status`, not just the absence
        of an error.
        """
        payload = self.build_order(symbol, action, quantity, price,
                                   odd_lot=odd_lot, opt_field=opt_field)
        body = await self._request("POST", "/api/v1/orders", json=payload)
        result = body.get("result") or {}
        return {
            "order_id": payload["id"],
            "status": result.get("status", "UNKNOWN"),
            "message": result.get("message", ""),
            "metadata": result.get("metadata") or {},
            "request": payload,
        }

    async def cancel_order(self, order_id: str) -> dict:
        body = await self._request("DELETE", f"/api/v1/orders/{segment(order_id, ORDER_ID, 'order id')}")
        result = body.get("result") or {}
        return {"order_id": order_id,
                "status": result.get("status", "UNKNOWN"),
                "message": result.get("message", "")}

    async def refresh_order(self, order_id: str) -> dict:
        """Re-check one order against the market. A read, despite the effect."""
        body = await self._request("GET", f"/api/v1/orders/{segment(order_id, ORDER_ID, 'order id')}")
        return body.get("result") or {}

    async def cancel_all(self) -> list:
        """Cancel every order the broker will still accept a cancel for.

        The shell's `cancel` does this with no confirmation. Here the
        confirmation is the UI's job; this function only reports per order so
        the page can show what actually happened rather than a count.
        """
        out = []
        for order in await self.orders():
            status = str(order.get("status", ""))
            oid = order.get("id") or order.get("ordno")
            if status not in CANCELLABLE:
                out.append({"order_id": oid, "symbol": order.get("symbol"),
                            "skipped": True, "status": status})
                continue
            try:
                res = await self.cancel_order(oid)
                res["symbol"] = order.get("symbol")
                res["skipped"] = False
                out.append(res)
            except BrokerError as exc:
                out.append({"order_id": oid, "symbol": order.get("symbol"),
                            "skipped": False, "status": "ERROR",
                            "message": str(exc)})
        return out

    # ── market data  (shell: ohlcv, kbars, replay, bidask) ────────────────────

    async def snapshot(self, symbol: str) -> Optional[dict]:
        """Latest OHLCV for one symbol.

        Know what the fields mean before plotting them: `close` and
        `timestamp` are this moment's, but open/high/low are the TRADING DAY's
        so far. It is not a one-minute bar.
        """
        body = await self._request("GET", f"/api/v1/market/{segment(symbol, SYMBOL, 'symbol')}/snapshot")
        return body.get("price")

    async def snapshots(self, symbols: list) -> list:
        """One snapshot per symbol. Serial, because the server serialises
        backend access anyway — firing these concurrently would just queue
        them behind each other on its lock."""
        out = []
        for sym in symbols:
            try:
                snap = await self.snapshot(sym)
            except BrokerError as exc:
                out.append({"symbol": sym, "error": str(exc)})
                continue
            if snap:
                out.append(snap)
            else:
                out.append({"symbol": sym, "error": "no price"})
        return out

    async def kbars(self, symbol: str, start: str, end: str,
                    interval: str = "1m") -> list:
        """Historical bars over [start, end). Server picks the data source."""
        if interval not in ("1m", "5m", "1h", "1d"):
            raise BrokerError(f"unsupported interval {interval!r}; "
                              f"use 1m, 5m, 1h or 1d")
        body = await self._request(
            "GET", f"/api/v1/market/{segment(symbol, SYMBOL, 'symbol')}/kbars",
            params={"start": start, "end": end, "interval": interval})
        return body.get("result") or []

    # ── clock  (shell: date, info) ────────────────────────────────────────────

    async def clock(self) -> dict:
        """The simulated clock.

        Every datetime on this API is an ISO 8601 **naive Asia/Taipei** value.
        Do not apply a timezone conversion to it; the engine does not, and
        doing so here would shift every bar by eight hours.
        """
        return await self._request("GET", "/api/v1/clock")

    async def is_market_open(self) -> bool:
        """Weekday and 09:00-13:30 on the simulated clock.

        Computed here rather than asked, because the server has no endpoint
        for it — the same local test `ArenaXMiddleWare.is_market_open` does.
        Note it answers for a common-lot session; the odd-lot session runs to
        14:30 and nothing in CJTrade consults it yet.
        """
        raw = (await self.clock()).get("mock_current_time")
        if not raw:
            return False
        moment = datetime.fromisoformat(raw)
        return (moment.weekday() < 5
                and moment.hour * 60 + moment.minute >= 9 * 60
                and moment.hour * 60 + moment.minute <= 13 * 60 + 30)
