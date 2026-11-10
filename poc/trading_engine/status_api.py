"""
Name:
  Trading engine status API
Description:
  A read-only HTTP surface on the master engine, so something outside the
  process can see what a run is doing while it is doing it. Loopback only,
  GET only, no route mutates engine state.
Usecase:
  Polled by the cjtrade shell and, later, by a separate web UI process.

WHY HTTP AND NOT A UNIX SOCKET
------------------------------
The eventual consumer is a browser, and a browser cannot connect to a unix
socket. Putting a proxy in front to translate would mean adding a process in
order to avoid opening a port, which is the wrong trade.

WHY THE ENGINE ONLY *SERVES* AND DOES NOT RENDER
------------------------------------------------
The web UI is a separate process. It has to outlive a run (you want to look at
the last one), it has to be restartable while a run continues, and the plan is
for it to execute user-written strategy code -- none of which belongs in the
process that holds the broker session. So this module exposes JSON and stops.

SECURITY POSTURE, STATED PLAINLY
--------------------------------
This is a local developer listener carrying account data: balances, positions,
fills and a session id. It is private by binding, not by authentication:

* `STATUS_HOST` is 127.0.0.1 and is deliberately NOT configurable. Only the
  port is, because two engines may want to run side by side.
* Every route is GET and reads in-memory state. There is no order path here.
* **No CORS header is sent, on purpose.** The browser is not meant to talk to
  this port -- the separate web process does, server-side, where CORS does not
  apply. Sending `Access-Control-Allow-Origin: *` would let any page the user
  happens to be visiting read this account data, and a loopback bind does not
  protect against the user's own browser.
* The Host header is checked against the loopback names. That is not
  authentication and must not be mistaken for it; it is the standard guard
  against DNS rebinding, where a hostile page points a domain it controls at
  127.0.0.1 so that its requests become same-origin and CORS stops helping.

If this ever needs to be reachable from another machine, the answer is an SSH
local port-forward, not a wider bind.
"""
import asyncio
import logging
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import is_dataclass
from datetime import datetime
from typing import Any
from typing import Optional

from aiohttp import web
from cjtrade.pkgs.models.backtest import BacktestResult

log = logging.getLogger("CJTrade.Engine")

# Not configurable. See the module docstring.
STATUS_HOST = "127.0.0.1"
# 8801/8802 are ArenaX, 8899 is cjtrade_system's API, 9876 is the form
# renderer, 5555/5556 are the engine's ZMQ pair. 8898 is clear.
DEFAULT_STATUS_PORT = 8898

# How long a /roundtrips answer is reused. The only endpoint that leaves the
# process, so the only one worth caching: under ReplayClock bars go by at ~80/s
# and a UI polling once a second would otherwise put a broker round trip on
# every second of the run.
ROUNDTRIP_TTL_S = 2.0

# Equity samples returned when the caller does not say. A year-long replay is
# ~64,000 samples, which is megabytes of JSON nobody asked for.
DEFAULT_EQUITY_LIMIT = 1000


@dataclass
class EngineView:
    """The read-only references a handler is allowed to look at.

    A bundle rather than a closure over main()'s locals so that what the HTTP
    layer can reach is written down in one place. Everything here is read
    without mutating it; the one call that leaves the process (the fill history
    behind /roundtrips) is documented at its handler.
    """

    session_id: str
    started_at: datetime         # wall clock, when the run began
    cfg: Any                     # EngineConfig (frozen)
    clock_name: str
    clock: Any
    hub: Any                     # EventHub -- bars, market_time
    recorder: Any                # RunRecorder -- equity_curve, session_id
    registry: Any                # BotRegistry -- latest, history
    gate: Any                    # RiskGate -- halted, halt_reason, exposures
    account_client: Any          # only for its control_plane, in a thread
    bots: list[str]


# ══════════════════════════════════════════════════════════════════════════════
#  JSON coercion
# ══════════════════════════════════════════════════════════════════════════════

def _jsonable(value: Any) -> Any:
    """Make one value safe for json_response.

    Dataclasses (BotStatus, RoundTrip) and datetimes are what actually turn up;
    everything else is already a JSON scalar or a container of them. Unknown
    types become their str() rather than raising, for the same reason
    protocol.wire_safe coerces instead of raising: a monitoring surface that
    can 500 on an unexpected value is worse than one that shows the repr.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)


# ══════════════════════════════════════════════════════════════════════════════
#  Views over engine state.  All of these are pure reads with no I/O.
# ══════════════════════════════════════════════════════════════════════════════

def _progress(view: EngineView) -> dict:
    """How far through the run we are.

    The three clocks do not share an interface beyond `finished` and `sleep`,
    so this feature-detects rather than assuming: only ReplayClock knows how
    many bars the run has in total, because only it was handed a timestamp
    list. Under a live clock the run has no end and `bars_total` is null --
    which is the honest answer, not a missing feature.
    """
    clock = view.clock
    total: Optional[int] = None
    stamps = getattr(clock, "timestamps", None)
    if stamps is not None:
        total = len(stamps)

    served = view.hub.bars
    return {
        "clock": view.clock_name,
        "bars_served": served,
        "bars_total": total,
        "fraction": round(served / total, 6) if total else None,
        # hub.market_time, not clock.now: every clock produces it, and it is
        # the timestamp the bots were actually given.
        "market_time": _jsonable(view.hub.market_time),
        "finished": bool(getattr(clock, "finished", False)),
    }


def _equity_now(view: EngineView) -> Optional[float]:
    """Latest portfolio value, from the curve the recorder already keeps.

    Not a broker call. The bar-end callback refreshes this every bar, so the
    freshest number available without I/O is the last sample -- and asking the
    broker from here would race the engine's own account read.
    """
    curve = view.recorder.equity_curve
    return curve[-1]["value"] if curve else None


def _equity_block(view: EngineView) -> dict:
    initial = view.recorder.initial_balance
    current = _equity_now(view)
    pnl = None if current is None else current - initial
    return {
        "initial": round(initial, 2),
        "current": current,
        "pnl": None if pnl is None else round(pnl, 2),
        "pnl_pct": None if pnl is None or initial <= 0 else round(pnl / initial * 100, 4),
        "samples": len(view.recorder.equity_curve),
        "as_of": view.recorder.equity_curve[-1]["time"] if view.recorder.equity_curve else None,
    }


def _risk_block(view: EngineView) -> dict:
    gate = view.gate
    lim = gate.limits
    return {
        "halted": gate.halted,
        "halt_reason": gate.halt_reason,
        "limits": {
            "max_notional_per_bot": lim.max_notional_per_bot,
            "max_orders_per_bar": lim.max_orders_per_bar,
            "max_loss_pct": lim.max_loss_pct,
            "duplicate_window_bars": lim.duplicate_window_bars,
        },
        # The property, not gate.exposure(bot_id): _exposure is a defaultdict,
        # so asking about a bot that has not traded would insert a key -- a
        # mutation, from a handler, on an object documented as not thread-safe.
        "exposure": {k: round(v, 2) for k, v in gate.exposures.items()},
    }


def _bot_block(view: EngineView) -> dict:
    """Each spawned bot's last word, or null if it has not spoken.

    Keyed off `view.bots` rather than off what the registry has heard, so a bot
    that died before its first report shows up as null instead of vanishing
    from the response.
    """
    latest = view.registry.latest
    return {bot_id: _jsonable(latest.get(bot_id)) for bot_id in view.bots}


# ══════════════════════════════════════════════════════════════════════════════
#  The one endpoint that leaves the process
# ══════════════════════════════════════════════════════════════════════════════

class _RoundTripCache:
    """Live round trips, computed from the server's fill history.

    Why the server and not master's own OrderReports: the backend applies the
    cost model when it settles a fill, so commission and tax exist only in its
    fill_history. That is the same reason RunRecorder.build_result goes there.

    Unlike build_result this does NOT touch AccountClient. It reads the control
    plane directly, which is a bare `requests.get` against an object holding
    nothing but a base URL, so it cannot interleave with the engine's own
    account sync. final_balance comes from the equity curve instead -- a
    mid-run number, and labelled as one.

    The lock does double duty: it keeps the TTL check and the fetch atomic, and
    it collapses a burst of pollers into one broker round trip instead of N.
    """

    def __init__(self, ttl: float = ROUNDTRIP_TTL_S):
        self.ttl = ttl
        self._lock = asyncio.Lock()
        self._payload: Optional[dict] = None
        self._at = 0.0

    async def get(self, view: EngineView) -> dict:
        async with self._lock:
            now = time.monotonic()
            if self._payload is not None and now - self._at < self.ttl:
                return dict(self._payload, cached=True)

            payload = await asyncio.to_thread(self._build, view)
            self._payload = payload
            self._at = time.monotonic()
            return dict(payload, cached=False)

    @staticmethod
    def _build(view: EngineView) -> dict:
        ctrl = view.account_client.control_plane
        if ctrl is None:
            # A real broker has no control plane. Not an error: it means this
            # information is not available on this path, and saying so beats a
            # 500 that looks like the engine is broken.
            return {"available": False,
                    "reason": "broker has no control plane (live broker?)",
                    "round_trips": []}

        raw = ctrl.get_backtest_state(session_id=view.session_id)
        if raw is None:
            return {"available": False,
                    "reason": "the server returned no fill history",
                    "round_trips": []}

        current = _equity_now(view)
        result = BacktestResult(
            initial_balance=view.recorder.initial_balance,
            # Mid-run, so "final" is a misnomer inherited from the dataclass.
            # Only compute_round_trips is used below, and it reads fill_history
            # alone, so these two only keep the constructor happy.
            final_balance=current if current is not None else view.recorder.initial_balance,
            equity_curve=list(view.recorder.equity_curve),
            fill_history=raw.get("fill_history", []),
            session_id=view.session_id,
            start_time=view.recorder.start_time,
            final_equity=current,
        )
        trips = result.compute_round_trips()
        wins = [t for t in trips if t.pnl > 0]
        return {
            "available": True,
            "fills": len(result.fill_history),
            "round_trips": [_jsonable(t) for t in trips],
            "closed": len(trips),
            "wins": len(wins),
            "losses": len(trips) - len(wins),
            "win_rate_pct": round(len(wins) / len(trips) * 100, 2) if trips else None,
            "realised_pnl": round(sum(t.pnl for t in trips), 2),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Server
# ══════════════════════════════════════════════════════════════════════════════

def build_app(view: EngineView, port: int = DEFAULT_STATUS_PORT) -> web.Application:
    """Routes and middleware. Separated from start() so it can be exercised
    without binding a socket."""

    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    cache = _RoundTripCache()

    @web.middleware
    async def _loopback_only(request: web.Request, handler):
        """Reject a request whose Host header is not a loopback name.

        NOT authentication -- it proves nothing about the caller. It closes the
        one hole a loopback bind leaves open: a page on the public internet can
        resolve a domain it owns to 127.0.0.1 and then its fetches are
        same-origin, so the absence of a CORS header stops protecting us. The
        Host header still carries the attacker's domain, which this catches.
        """
        if request.headers.get("Host") not in allowed_hosts:
            return web.json_response(
                {"error": "this endpoint only answers to a loopback Host header"},
                status=403)
        return await handler(request)

    async def health(_request):
        return web.json_response({
            "ok": True,
            "session_id": view.session_id,
            "bars_served": view.hub.bars,
        })

    async def status(_request):
        cfg = view.cfg
        return web.json_response({
            "session_id": view.session_id,
            "started_at": view.started_at.isoformat(),
            "uptime_s": round((datetime.now() - view.started_at).total_seconds(), 1),
            "config": {
                "broker": cfg.broker,
                "backend_mode": cfg.backend_mode,
                "symbols": list(cfg.symbols),
                "requested_balance": cfg.initial_balance,
                "duration_days": cfg.duration_days,
                "playback_speed": cfg.playback_speed,
                "start_date": cfg.start_date,
            },
            "progress": _progress(view),
            "equity": _equity_block(view),
            "risk": _risk_block(view),
            "bots": _bot_block(view),
        })

    async def bots(_request):
        return web.json_response(_bot_block(view))

    async def bot_history(request):
        """This bot's recent per-bar reports, oldest first.

        The registry's ring buffer is shared across bots, so a two-bot run
        holds half as much per bot. That is the point of a bounded buffer: it
        answers "what was it doing just before that", not "replay the run".
        """
        bot_id = request.match_info["bot_id"]
        if bot_id not in view.bots:
            return web.json_response({"error": f"no such bot: {bot_id}"}, status=404)
        limit = _int_param(request, "limit", 0)
        rows = [s for s in list(view.registry.history) if s.bot_id == bot_id]
        if limit > 0:
            rows = rows[-limit:]
        return web.json_response({
            "bot_id": bot_id,
            "kept": len(rows),
            "capacity": view.registry.history.maxlen,
            "history": [_jsonable(s) for s in rows],
        })

    async def equity(request):
        """The equity curve, tail-truncated by default (limit=0 for all)."""
        limit = _int_param(request, "limit", DEFAULT_EQUITY_LIMIT)
        curve = list(view.recorder.equity_curve)
        total = len(curve)
        if limit > 0:
            curve = curve[-limit:]
        return web.json_response({
            "initial_balance": view.recorder.initial_balance,
            "start_time": view.recorder.start_time,
            "samples": total,
            "returned": len(curve),
            "truncated": len(curve) < total,
            "curve": curve,
        })

    async def roundtrips(_request):
        return web.json_response(await cache.get(view))

    app = web.Application(middlewares=[_loopback_only])
    # GET only. Nothing here places, cancels or amends an order: the engine's
    # control surface is the ZMQ intent socket, and widening this one to accept
    # writes would make a drive-by request from the user's browser able to
    # trade, which no amount of CORS policy would stop.
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_get("/bots", bots)
    app.router.add_get("/bots/{bot_id}/history", bot_history)
    app.router.add_get("/equity", equity)
    app.router.add_get("/roundtrips", roundtrips)
    return app


def _int_param(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


async def start(view: EngineView, port: int = DEFAULT_STATUS_PORT):
    """Bind the status API. Returns the runner, for the caller to clean up.

    Returns None rather than raising if the port is taken: a second engine on
    the same machine should lose its status endpoint, not its run.
    """
    runner = web.AppRunner(build_app(view, port), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, STATUS_HOST, port).start()
    except OSError as e:
        await runner.cleanup()
        log.warning(f"[Status] no status API on {STATUS_HOST}:{port} ({e}) — "
                    f"another engine may already have it")
        return None
    log.info(f"[Status] http://{STATUS_HOST}:{port}/status  "
             f"(read-only, loopback only)")
    return runner
