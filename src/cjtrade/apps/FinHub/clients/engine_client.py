"""Client for the trading engine's read-only status API.

Mirrors `apps/CJTrade/status_api.py`. Everything here is a GET; the
engine exposes no write surface and this client must not grow one — the
engine's control path is its ZMQ intent socket, and a run is started and
stopped through `RunSupervisor`, not over HTTP.

"The engine is not running" is the normal case, not an error: most of the time
there is no run in flight. So the methods raise one specific exception for it
and the routes turn that into a quiet "no run" rather than a 500.
"""
from typing import Any
from typing import Callable
from typing import Optional

import httpx
from cjtrade.pkgs.logger import get_logger

log = get_logger("FinHub.engine")


class EngineUnavailable(RuntimeError):
    """No engine answered. Usually means no run is in flight."""


class EngineClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        # Short by default. These are all in-memory reads on the engine's side
        # except /roundtrips, which it caches for 2s behind one broker call, so
        # anything slower than this means the engine is wedged and the UI is
        # better off being told than waiting.
        self.timeout = timeout
        # How to find the current run's control-plane capability. A callable
        # rather than a stored value, because the token belongs to a run and
        # this client outlives every run: caching it here would mean a stale
        # token after a restart and a forgotten one after a stop, and both
        # failures look like "the engine refused us" at the worst moment.
        # Whoever starts the engine sets this; see main.py.
        self.token_provider: Optional[Callable[[], Optional[str]]] = None

    @property
    def control_token(self) -> Optional[str]:
        return self.token_provider() if self.token_provider else None

    def _headers(self) -> dict:
        token = self.control_token
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params,
                                        headers=self._headers())
        except httpx.RequestError as exc:
            raise EngineUnavailable(f"{url}: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code in (401, 403):
            # Distinguished from "the engine is down", because the two need
            # different fixes: this one means FinHub and the engine disagree
            # about the token, which happens if FinHub restarted while a run
            # it started was still going.
            raise EngineUnavailable(
                f"{url}: the engine refused FinHub's control token "
                f"(HTTP {resp.status_code}) — it is probably from a run that "
                f"FinHub no longer remembers starting")
        if resp.status_code >= 400:
            raise EngineUnavailable(f"{url}: HTTP {resp.status_code}")
        return resp.json()

    async def stop_bot(self, bot_id: str, reason: str) -> dict:
        """Tell the engine to stop one bot, now.

        The only write this client makes. Needs the control token: without one
        the engine answers 503 and says it has no control plane, which is the
        honest answer for an engine FinHub did not start.
        """
        if not self.control_token:
            raise EngineUnavailable(
                "no control token for this run, so there is nothing to "
                "authorise a stop with — only a run FinHub started can be "
                "controlled from here")
        url = f"{self.base_url}/bots/{bot_id}/stop"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers(),
                                         json={"reason": reason})
        except httpx.RequestError as exc:
            raise EngineUnavailable(f"{url}: {exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error", "")
            except Exception:
                detail = resp.text[:200]
            raise EngineUnavailable(f"{url}: HTTP {resp.status_code} {detail}")
        return resp.json()

    async def is_up(self) -> bool:
        try:
            await self._get("/health")
            return True
        except EngineUnavailable:
            return False

    async def health(self) -> dict:
        return await self._get("/health")

    async def status(self) -> dict:
        """Everything about the run in one read: config, progress, equity,
        risk, and each bot's last report."""
        return await self._get("/status")

    async def bots(self) -> dict:
        """bot_id -> its last report, or None for a bot that never spoke."""
        return await self._get("/bots")

    async def bot_history(self, bot_id: str, limit: int = 0) -> Optional[dict]:
        """That bot's recent per-bar reports. None when the id is unknown.

        The engine's buffer is shared across bots and bounded, so this answers
        "what was it doing just before that", not "replay the run".
        """
        return await self._get(f"/bots/{bot_id}/history", {"limit": limit})

    async def equity(self, limit: int = 1000) -> dict:
        """The equity curve, newest `limit` samples. 0 means all of it."""
        return await self._get("/equity", {"limit": limit})

    async def roundtrips(self) -> dict:
        """Closed trades, win rate and realised P&L, computed live.

        The one engine call that leaves its process (it reads the broker's fill
        history), which is why the engine caches it. Do not poll faster than a
        second or two.
        """
        return await self._get("/roundtrips")
