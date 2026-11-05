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

logging.basicConfig(
    level=logging.INFO,      # DEBUG drowns the drift warnings in urllib3 noise
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.trading_engine2")

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
    """ArenaX advances its own clock at `speed`x; we only pace our sampling.

    This is main.py's behaviour with two defects fixed, both invisible to the
    engine:

    1. `speed` is read from the server (see for_server below), not configured
       separately. In main.py the engine's `60 / playback_speed` and ArenaX's own
       playback_speed are two numbers that have to be set equal by hand; when
       they differ, the real sampling gap becomes `arenax_speed / engine_speed`
       market seconds and every bar in between is simply never seen.

    2. Sleeps until an absolute deadline rather than for a fixed duration.
       Market time keeps moving while we fetch snapshots, so a plain
       sleep(interval) makes each cycle take `interval + work` and overshoot by
       `work * speed` market seconds, every cycle, forever.

    Both only help while work < interval. Past that the machine cannot keep up
    and bars really are skipped -- so it says so, instead of quietly thinning
    the series. That warning is the point: it tells you whether this clock is
    good enough for your speed, or whether you need ReplayClock.
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
    """Logical time is `timestamps[cursor]`, and only sleep() moves the cursor.

    Nothing else advances time -- not the wall clock, not the server -- so the
    engine cannot be outrun and no bar can be skipped. A slow bot or a 10-second
    LLM call costs real seconds and zero market seconds. Two runs over the same
    data produce the same bars, in the same order, every time.

    sleep() costs no real time when speed is None (backtest, flat out), or
    `market_seconds / speed` when you want to watch it go by (demo).
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
        # Advance to the first real bar at or after now + market_seconds. Asking
        # for 60 on 1m data moves exactly one bar; asking for 300 moves five.
        target = self.now + timedelta(seconds=market_seconds)
        while not self.finished and self.timestamps[self.i] < target:
            self.i += 1
        # Blocking HTTP, so keep it off the event loop. The engine never sees
        # this call -- stepping the server is the clock's private business.
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

        # Align the server's start_date with our timeline origin before stepping.
        # The fill path measures minute offsets from start_date
        # (base_backend.py:890) and derives fill_time from it (line 842), so a
        # mismatched start_date corrupts fills even while snapshot() stays right
        # (it binary-searches instead). set_system_time is the correct tool here:
        # setting the start date is literally its job.
        #   auto_preload_data=False is REQUIRED -- True clears historical_data
        #   and refetches it (brokerside_server.py:618).
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


# ══════════════════════════════════════════════════════════════════════════════
#  EventHub — same as main.py apart from the clock.
# ══════════════════════════════════════════════════════════════════════════════

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
        log.debug(f"[Master] Broadcasting {symbol} at {tick['p']}...")

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

    mw = client.broker_api.middleware    # public attr, arenax_broker_api.py:49

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
