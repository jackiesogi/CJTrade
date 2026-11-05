"""
poc/trading_engine/main2.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Clock variant of main.py. main.py is left untouched; run either to compare.

The only change to the engine is one line in _reload_loop:

    main.py :   await asyncio.sleep(60 / self.playback_speed)
    main2.py:   await self.clock.sleep(BAR_INTERVAL_SEC)

`clock.sleep(60)` means "advance 60 seconds of MARKET time". How much real time
that costs is the clock's business, not the engine's. So the engine holds no
playback speed, no mode flag, and never calls the backend to set a time --
but the loop still reads like a loop that waits and goes round again.

Three clocks, same interface:

    RealtimeClock   60 market seconds = 60 real seconds. Touches no broker, so
                    every live broker shares it (sinopac / yuanta / cathay /
                    ArenaX real+paper). Runs today.

    ScaledClock     ArenaX keeps driving its own clock; we just sample it. Reads
                    playback_speed FROM THE SERVER so the two cannot disagree,
                    and sleeps to an absolute deadline so per-cycle work does
                    not silently thin the series. Runs today, no server change.

    ReplayClock     Single time authority: logical time is timestamps[cursor],
                    and it moves only when the engine sleeps. Nothing else
                    advances it, so no bar can be missed and two runs over the
                    same data are identical.
                    NEEDS ArenaXMiddleWare.set_market_time() -- see
                    doc/CJENGINE_DETERMINISTIC_REPLAY_SPEC.md §5.2-5.4. Raises a
                    clear error until that lands.

Pick one with MODE near the bottom.
"""
import asyncio
import logging
import random
import sys
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import msgpack
import zmq.asyncio
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product

# ── Logging ───────────────────────────────────────────────────────────────────
# Two independent knobs, because the two kinds of noise have nothing to do with
# each other and lumping them under one level forces a bad trade: INFO hides the
# price feed, DEBUG buries everything under urllib3.
LOG_LEVEL = logging.DEBUG        # the engine's own chatter
FEED_LOG_LEVEL = logging.DEBUG   # one line per symbol per bar; raise to INFO to mute

logging.basicConfig(
    level=LOG_LEVEL,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)

# urllib3 emits two DEBUG lines per HTTP call ("Starting new HTTP connection"
# plus the request line). Replay mode makes 5 calls per bar, so at DEBUG these
# outnumber our own output roughly 10:1 and hide the drift warnings entirely.
# Silence the transport, not ourselves.
for _noisy in ("urllib3", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger("poc.trading_engine2")

# Separate logger for the per-tick feed so it can be muted on its own: at high
# playback speed this is thousands of lines a second, which is useful when
# eyeballing one bar and useless when watching a two-month replay.
log_feed = logging.getLogger("poc.trading_engine2.feed")
log_feed.setLevel(FEED_LOG_LEVEL)

CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

BOT_C_SCRIPT = Path(__file__).resolve().parent / "bot_c.py"

INITIAL_BALANCE = 1_000_000.0
ARENAX_PORT = 8802
SYMBOLS = ["0050", "2357", "2317", "00919"]
BAR_INTERVAL_SEC = 60        # market seconds between samples == 1m bars


# ══════════════════════════════════════════════════════════════════════════════
#  Clocks.  Each one answers: "the engine wants N market seconds to pass -- what
#  does that cost in real time, and does anything need to be told?"
# ══════════════════════════════════════════════════════════════════════════════

class RealtimeClock:
    """Market time is real time."""

    finished = False

    async def sleep(self, market_seconds: float) -> None:
        await asyncio.sleep(market_seconds)


class ScaledClock:
    """
    ArenaX advances its own clock at `speed`x; we only pace our sampling.
    #   How?
    #     1. Ask ArenaX config: playback speed
    #     2. Set scaled speed for this clock
    """

    finished = False

    def __init__(self, speed: float):
        self.speed = speed
        self._deadline: float | None = None

    @classmethod
    def for_server(cls, mw) -> "ScaledClock":
        t = mw.get_system_time()
        if not t:
            raise RuntimeError("ArenaX /control/get-time returned nothing — is the server up?")
        speed = float(t["playback_speed"])
        log.info(f"[Clock] scaled: server playback_speed={speed}x")
        return cls(speed)

    async def sleep(self, market_seconds: float) -> None:
        wall = market_seconds / self.speed
        now = time.monotonic()
        if self._deadline is None:
            self._deadline = now
        self._deadline += wall

        slack = self._deadline - now
        if slack > 0:
            await asyncio.sleep(slack)
        else:
            skipped = -slack * self.speed / market_seconds
            log.warning(
                f"[Clock] behind by {-slack*1000:.0f}ms (~{skipped:.1f} bars skipped) — "
                f"work per cycle exceeds the {wall*1000:.1f}ms budget at "
                f"playback_speed={self.speed}x"
            )
            self._deadline = time.monotonic()      # re-baseline, don't accrue debt


class ReplayClock:
    """
    Logical time is `timestamps[cursor]`, and only sleep() moves the cursor.
    #   How?
    #     1. Engine finish broadcasting prices at this ts.
    #     2. Call ArenaX mw api.
    #     3. ArenaX server time advances.
    #   auto_preload_data=False is REQUIRED -- True clears historical_data
    """

    def __init__(self, mw, timestamps: list[datetime], speed: float | None = None):
        self.mw = mw
        self.timestamps = timestamps
        self.speed = speed
        self.i = 0
        mw.set_market_time(timestamps[0])         # park the server on bar 0

    @property
    def finished(self) -> bool:
        return self.i >= len(self.timestamps) - 1

    @property
    def now(self) -> datetime:
        return self.timestamps[self.i]

    async def sleep(self, market_seconds: float) -> None:
        # Advance to the first real bar at or after now + market_seconds.
        target = self.now + timedelta(seconds=market_seconds)
        while not self.finished and self.timestamps[self.i] < target:
            self.i += 1

        # Blocking wait
        await asyncio.to_thread(self.mw.set_market_time, self.now)
        if self.speed is not None:
            await asyncio.sleep(market_seconds / self.speed)

    @classmethod
    def for_server(cls, mw, symbols, start, end, interval="1m", speed=None) -> "ReplayClock":
        if not hasattr(mw, "set_market_time"):
            raise RuntimeError(
                "ArenaXMiddleWare.set_market_time() is missing — ReplayClock cannot "
                "step the server clock without it.\n"
                "Apply changes 1-3 of doc/CJENGINE_DETERMINISTIC_REPLAY_SPEC.md "
                "(§5.2-5.4), or use MODE='scaled' for now."
            )

        timestamps = _bar_timestamps(mw, symbols, start, end, interval)
        if not timestamps:
            raise ValueError(f"ArenaX returned no kbars for {symbols} in [{start}, {end})")

        # Set ArenaX server time.
        mw.set_system_time(mock_init_time=timestamps[0].isoformat(),
                           auto_start_progress=False, auto_preload_data=False)

        log.info(f"[Clock] replay: {len(timestamps)} bars, "
                 f"{timestamps[0]} .. {timestamps[-1]}, "
                 f"{'full speed' if speed is None else f'{speed}x'}")
        return cls(mw, timestamps, speed)


def _bar_timestamps(mw, symbols, start, end, interval) -> list[datetime]:
    """Union of every symbol's bar timestamps, sorted.

    Union, not intersection: a symbol halted for a day should not delete that day
    from everyone else's timeline.
    """
    seen: set[datetime] = set()
    for sym in symbols:
        # get_kbars returns list[dict] with a "timestamp" key -- raw JSON, not
        # Kbar objects (arenax_middleware.py:188).
        for row in mw.get_kbars(sym, start, end, interval):
            raw = row.get("timestamp")
            if raw is None:
                continue
            seen.add(raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw)))
    return sorted(seen)


class EventHub:
    def __init__(self, account_client: AccountClient, clock):
        self.client = account_client
        self.clock = clock
        self.watch_list = set()
        self.pub_socket = None
        self._last_price: dict[str, float] = {}
        self.bars = 0

    async def _broadcast(self, tick: dict):
        symbol = tick["s"]
        await self.pub_socket.send_multipart([symbol.encode('utf-8'), msgpack.packb(tick)])
        log_feed.debug(f"[Master] Broadcasting {symbol} at {tick['p']}...")

    def _snapshot(self, symbol: str) -> dict:
        if self.client is not None:
            return self._snapshot_real(symbol)
        return self._snapshot_mock(symbol)

    def _snapshot_real(self, symbol: str) -> dict:
        snap = self.client.get_snapshots([Product(symbol=symbol)])[0]
        return {"s": snap.symbol, "p": snap.close, "t": snap.timestamp.timestamp()}

    def _snapshot_mock(self, symbol: str) -> dict:
        # Unseeded — fine for eyeballing the plumbing, but don't build a
        # reproducibility baseline on this path.
        prev = self._last_price.get(symbol, 100.0)
        price = max(50.0, min(200.0, prev + random.gauss(0, 1.2)))
        self._last_price[symbol] = price
        return {"s": symbol, "p": round(price, 2), "t": time.time()}

    async def _reload_loop(self):
        """Sample every watched symbol, publish, wait one bar, repeat.

        `self.clock.sleep(60)` waits 60 seconds of MARKET time. Under
        RealtimeClock that is 60 real seconds; under ScaledClock it is
        60/speed; under ReplayClock it costs nothing at all and just steps to
        the next bar. Same line either way -- that is the only reason this loop
        needs no mode branch.
        """
        started = time.monotonic()
        while not self.clock.finished:
            # sorted(), not list(): fixed symbol order per bar, so a multi-symbol
            # run is reproducible instead of following set iteration order.
            for symbol in sorted(self.watch_list):
                try:
                    # Blocking network I/O in real mode — keep it off the loop.
                    tick = await asyncio.to_thread(self._snapshot, symbol)
                except Exception as e:
                    log.warning(f"[Master] Snapshot fetch failed for {symbol}: {e}")
                    continue
                await self._broadcast(tick)

            self.bars += 1
            if self.bars % 500 == 0:
                log.info(f"[Master] {self.bars} bars served")

            await self.clock.sleep(BAR_INTERVAL_SEC)

        # Only reachable with ReplayClock; the live clocks never finish.
        elapsed = time.monotonic() - started
        log.info(f"[Master] Replay complete — {self.bars} bars in {elapsed:.1f}s "
                 f"({self.bars/max(elapsed, 1e-9):.0f} bars/s)")

    def subscribe_price_feed(self, symbol: str):
        self.watch_list.add(symbol)

    def start(self, pub_socket):
        self.pub_socket = pub_socket
        return asyncio.create_task(self._reload_loop())


# ══════════════════════════════════════════════════════════════════════════════
#  ExecutionEngine — unchanged from main.py.
#
#  Note what is absent: no clock, no set_market_time, no mode check. Under
#  ReplayClock the server was already parked on bar t before the bot saw it, so
#  an order placed while handling bar t lands on a server whose mock time is t.
#  It lines up without this class knowing any of it.
# ══════════════════════════════════════════════════════════════════════════════

class ExecutionEngine:
    def __init__(self, account_client: AccountClient | None):
        self.client = account_client
        self._ledger: dict[str, dict] = {}

    def _account_for(self, bot_id: str) -> dict:
        return self._ledger.setdefault(bot_id, {"balance": INITIAL_BALANCE, "positions": {}})

    async def execute(self, order: dict) -> dict:
        if self.client is not None:
            return await asyncio.to_thread(self._execute_via_broker, order)
        return self._execute_paper(order)

    def _execute_via_broker(self, order: dict) -> dict:
        symbol, action, qty, price = order["symbol"], order["action"], order["qty"], order["price"]
        try:
            if action == "BUY":
                result = self.client.buy_stock(symbol=symbol, quantity=qty, price=price, intraday_odd=True)
            elif action == "SELL":
                result = self.client.sell_stock(symbol=symbol, quantity=qty, price=price, intraday_odd=True)
            else:
                return self._reply_from_broker(order, "REJECTED", 0, f"unknown action {action}")
        except Exception as e:
            return self._reply_from_broker(order, "REJECTED", 0, str(e))

        if result.status != OrderStatus.FILLED:
            return self._reply_from_broker(order, "REJECTED", 0,
                                           f"{result.status}: {result.message}")
        return self._reply_from_broker(order, "FILLED", qty, order.get("reason", ""))

    def _reply_from_broker(self, order: dict, status: str, filled_qty: int, reason: str) -> dict:
        symbol = order["symbol"]
        balance = self.client.get_balance()
        pos = next((p for p in self.client.get_positions() if p.symbol == symbol), None)
        position = {"quantity": pos.quantity, "avg_cost": pos.avg_cost} if pos else {"quantity": 0, "avg_cost": 0.0}
        return {
            "b_id": order["b_id"], "status": status, "action": order.get("action"),
            "symbol": symbol, "qty": filled_qty, "price": order.get("price"), "t": time.time(),
            "balance": balance, "position": position, "reason": reason,
        }

    def _execute_paper(self, order: dict) -> dict:
        acct = self._account_for(order["b_id"])
        symbol, action, qty, price = order["symbol"], order["action"], order["qty"], order["price"]

        if action == "BUY":
            if qty <= 0 or price * qty > acct["balance"]:
                return self._reply(order, acct, "REJECTED", 0,
                                   "insufficient balance" if qty > 0 else "invalid qty")
            acct["balance"] -= price * qty
            pos = acct["positions"].setdefault(symbol, {"quantity": 0, "avg_cost": 0.0})
            total = pos["quantity"] + qty
            pos["avg_cost"] = (pos["quantity"] * pos["avg_cost"] + qty * price) / total
            pos["quantity"] = total
        elif action == "SELL":
            pos = acct["positions"].get(symbol)
            if not pos or pos["quantity"] < qty or qty <= 0:
                return self._reply(order, acct, "REJECTED", 0, "no/insufficient position")
            acct["balance"] += price * qty
            pos["quantity"] -= qty
            if pos["quantity"] == 0:
                pos["avg_cost"] = 0.0
        else:
            return self._reply(order, acct, "REJECTED", 0, f"unknown action {action}")

        return self._reply(order, acct, "FILLED", qty, order.get("reason", ""))

    def _reply(self, order: dict, acct: dict, status: str, filled_qty: int, reason: str) -> dict:
        symbol = order["symbol"]
        return {
            "b_id": order["b_id"], "status": status, "action": order.get("action"),
            "symbol": symbol, "qty": filled_qty, "price": order.get("price"), "t": time.time(),
            "balance": acct["balance"],
            "position": dict(acct["positions"].get(symbol, {"quantity": 0, "avg_cost": 0.0})),
            "reason": reason,
        }


ctx = zmq.asyncio.Context()


async def handle_orders(pull_socket, pub_socket, engine: ExecutionEngine):
    log.info("[Master] Started order execution loop...")
    while True:
        try:
            order = msgpack.unpackb(await pull_socket.recv())
            fill = await engine.execute(order)
            log.info(f"[Master] {fill['status']} {fill['action']} {fill['symbol']} "
                     f"x{fill['qty']} @ {fill['price']} for {fill['b_id']} ({fill['reason']})")
            await pub_socket.send_multipart([fill["b_id"].encode('utf-8'), msgpack.packb(fill)])
        except Exception as e:
            log.info(f"[Master] Got exception while handling order: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Init task — the only place that knows which broker and which mode this is.
# ══════════════════════════════════════════════════════════════════════════════

MODE = "scaled"          # "scaled" | "replay" | "realtime"
REPLAY_START = "2025-09-01"
REPLAY_END = "2025-12-01"
REPLAY_SPEED = None     # None = full speed; 120.0 = watchable demo


def build_clock(client: AccountClient, mode: str, symbols: list[str]):
    """Choose the time regime. Everything downstream is broker-agnostic.

    This `if` is the entire broker/mode-specific surface. Putting sinopac here
    means returning RealtimeClock() and changing nothing else.
    """
    if mode == "realtime":
        return RealtimeClock()           # note: never touches `client`

    mw = client.control_plane            # None for a live broker
    if mw is None:
        raise RuntimeError(f"broker {client.get_broker_name()!r} has no control "
                           f"plane — mode={mode!r} needs a simulated exchange")

    if mode == "scaled":
        return ScaledClock.for_server(mw)
    if mode == "replay":
        return ReplayClock.for_server(mw, symbols, REPLAY_START, REPLAY_END,
                                      interval="1m", speed=REPLAY_SPEED)
    raise ValueError(f"unknown mode: {mode!r}")


async def main():
    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind(CJ_ENGINE_SOCKET_SUB_PRICE)
    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind(CJ_ENGINE_SOCKET_PUSH_STATE)

    account_client = AccountClient(broker_type=BrokerType.ARENAX,
                                   arenax_port=ARENAX_PORT, api_key="testkey123")
    if not await asyncio.to_thread(account_client.connect):
        log.error(f"[Master] Failed to connect to ArenaX broker (port {ARENAX_PORT}) — aborting.")
        return

    # Before spawning bots: ReplayClock does its kbar fetch and clock alignment
    # here, and there is no point feeding bots if that fails.
    try:
        clock = await asyncio.to_thread(build_clock, account_client, MODE, SYMBOLS)
    except Exception as e:
        log.error(f"[Master] Could not build clock for mode={MODE!r}: {e}")
        account_client.disconnect()
        return

    proc = await asyncio.create_subprocess_exec(sys.executable, '-u', str(BOT_C_SCRIPT), "Bot_C")
    await asyncio.sleep(2)       # let the subprocess finish its ZMQ connect

    hub = EventHub(account_client=account_client, clock=clock)
    for s in SYMBOLS:
        hub.subscribe_price_feed(s)

    engine = ExecutionEngine(account_client=account_client)
    asyncio.create_task(handle_orders(pull_socket, pub_socket, engine))

    try:
        await hub.start(pub_socket)
    finally:
        log.info("[Master] Terminating all bots...")
        try:
            proc.terminate()
            await proc.wait()
        except Exception:
            pass
        log.info("[Master] Trading engine terminated.")
        account_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
