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
import json
import logging
import os
import random
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Awaitable
from typing import Callable

import protocol
import status_api
import zmq.asyncio
from cjtrade.pkgs import paths
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.models.backtest import BacktestResult
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Exchange
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.risk import RiskGate
from cjtrade.pkgs.risk import RiskLimits
from cjtrade.pkgs.ui.engine import FormEngine
from protocol import OrderIntent
from protocol import OrderReport
from protocol import PriceUpdate

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
#
# matplotlib and PIL are here for the same reason at the other end of the run:
# rendering the end-of-run tearsheet emits a dozen DEBUG lines about font
# caches and axis titles immediately before the summary we actually want read.
for _noisy in ("urllib3", "asyncio", "matplotlib", "PIL"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger("poc.trading_engine2")

# Separate logger for the per-tick feed so it can be muted on its own: at high
# playback speed this is thousands of lines a second, which is useful when
# eyeballing one bar and useless when watching a two-month replay.
log_feed = logging.getLogger("poc.trading_engine2.feed")
log_feed.setLevel(FEED_LOG_LEVEL)

BOT_C_SCRIPT = Path(__file__).resolve().parent / "bot_c.py"

ARENAX_PORT = 8802
BAR_INTERVAL_SEC = 60        # market seconds between samples == 1m bars

# The same form cjtrade_system is launched with (poc/backtest_full_simulation.sh
# evals it). Sharing the file means the two apps ask the identical questions and
# share one persisted answer set, instead of drifting into two copies.
FORM_SCHEMA = Path(__file__).resolve().parents[1] / "backtest_full_simulation.toml"

# Which clock implementation to exercise. Deliberately NOT a form field: the
# form asks which ArenaX backend to run against (backtest / paper / demo), which
# is a question about the market being simulated. This is a question about the
# engine, and "replay" additionally needs a server that implements
# set_market_time, so it cannot be derived from the backend mode alone.
CLOCK = "replay"             # "scaled" | "replay" | "realtime"

# ── Risk limits ───────────────────────────────────────────────────────────────
# The master's own controls, not the broker's. Module constants rather than form
# fields because they are properties of this engine, not of the market being
# simulated. None switches a control off.
RISK_MAX_ORDERS_PER_BAR = 3      # a strategy firing more than this per bar is a bug
RISK_MAX_LOSS_PCT = 0.25         # equity down this far halts new orders
RISK_DUPLICATE_WINDOW_BARS = 3   # identical order within this many bars is refused

# Consecutive bars the account can be unreadable before the gate halts. In
# bars rather than seconds because the quantity that matters is how many bars
# the bots traded while the kill switch was blind.
ACCOUNT_READ_MAX_FAILURES = 5

# ── Bot monitoring ────────────────────────────────────────────────────────────
# A bot reports once per bar, so silence is measured in bars here (the bot's own
# side measures it in seconds, because it cannot know the playback rate).
BOT_SILENT_BARS = 20             # no status for this many bars -> say so
BOT_STATUS_HISTORY = 500         # per-bar snapshots kept, across all bots
BOT_STATUS_EVERY = 500           # log a status line this often, with bars served

# Where the read-only status API listens. The host is not settable -- see
# status_api's module docstring. The port is, so two engines can coexist.
STATUS_PORT = int(os.environ.get("CJ_ENGINE_STATUS_PORT", status_api.DEFAULT_STATUS_PORT))


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
        t = mw.get_market_time()
        if not t:
            raise RuntimeError("ArenaX GET /api/v1/clock returned nothing — is the server up?")
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
        # None means flat out. Any positive number is market seconds per real
        # second, so 1.0 replays at the speed the market actually moved.
        self.speed = speed
        self.i = 0
        # Pacing is deadline-based rather than "sleep the budget each bar".
        # Sleeping the budget adds the time the bar's own work took on top of
        # it, so the error compounds: at 1200x the budget is 50ms and a bar
        # costs ~16ms, which is a third of the requested rate lost. Tracking a
        # deadline spends the work out of the budget instead of after it.
        #
        # ScaledClock has its own copy of this. Not shared, because it is not
        # reachable on any current path (CLOCK is "replay" and live modes take
        # RealtimeClock), and extracting a helper that only one caller uses is
        # not worth touching code nothing exercises.
        self._deadline: float | None = None
        self._behind_bars = 0
        self._behind_worst_ms = 0.0
        self._last_behind_log = 0.0
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
        if not self.speed:
            return                         # flat out: no pacing at all

        # Charged per bar, not per market second, so `speed` is a WITHIN-SESSION
        # rate. Inside a trading session the two are the same thing -- measured
        # on 2317, 3958 of 3989 consecutive bars are exactly 60s apart -- so one
        # market minute really does cost 60/speed real seconds there.
        #
        # Between sessions they are not. The cursor crosses 19.5 hours
        # overnight, and 67.5 hours over a weekend, for the price of one bar.
        # That is deliberate: pacing those faithfully would have a 60x replay
        # sit idle for 19.5 real minutes every simulated night. The consequence
        # is that end-to-end acceleration is higher than the number asked for --
        # 3.9x higher over a 2-day window, 7.3x over 20 days -- which for_server
        # reports at startup rather than leaving it to be discovered.
        wall = market_seconds / self.speed
        now = time.monotonic()
        if self._deadline is None:
            self._deadline = now
        self._deadline += wall

        slack = self._deadline - now
        if slack > 0:
            await asyncio.sleep(slack)
            return

        # Asked for more than the machine can deliver. Said out loud, because
        # the alternative is a run that silently goes at whatever rate it can
        # and reports the speed you asked for.
        self._behind_bars += 1
        self._behind_worst_ms = max(self._behind_worst_ms, -slack * 1000)
        # Rate-limited: at 30000x the budget is 2ms and every bar would be
        # late, which is thousands of identical lines.
        if now - self._last_behind_log >= 5.0:
            self._last_behind_log = now
            log.warning(
                f"[Clock] cannot keep up with {self.speed:g}x — "
                f"{self._behind_bars} bar(s) late, worst by "
                f"{self._behind_worst_ms:.0f}ms against a "
                f"{wall*1000:.1f}ms budget. The replay is running as fast as it "
                f"can, which is slower than requested."
            )
            self._behind_bars = 0
            self._behind_worst_ms = 0.0
        self._deadline = time.monotonic()      # re-baseline, don't accrue debt

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
        mw.set_timeline_origin(mock_init_time=timestamps[0].isoformat(),
                           auto_start_progress=False, auto_preload_data=False)

        log.info(f"[Clock] replay: {len(timestamps)} bars, "
                 f"{timestamps[0]} .. {timestamps[-1]}, "
                 f"{_pace_summary(timestamps, speed)}")
        return cls(mw, timestamps, speed)


def _human_duration(seconds: float) -> str:
    """Rough wall-clock duration, for telling someone what they just asked for."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.1f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def _pace_summary(timestamps: list[datetime], speed: float | None) -> str:
    """What a requested speed actually means for this timeline.

    Reports two numbers because they differ and only one of them is the one on
    the label. `speed` is a within-session rate: it buys 60 market seconds for
    60/speed real seconds, which is exact while the market is open. Over the
    whole replay it understates the acceleration, because the hours the market
    is shut are crossed for the price of one bar -- 19.5 of them overnight,
    67.5 over a weekend.

    A 20-day replay of 2317 spans 484 hours of market time in 3,989 bars, so
    asking for 600x gets you about 4,400x end to end. Printing only the first
    number would be the kind of true-but-misleading that costs an afternoon.
    """
    if not speed:
        return "flat out (no pacing)"
    wall_s = len(timestamps) * BAR_INTERVAL_SEC / speed
    out = (f"{speed:g}x within a session → about {_human_duration(wall_s)} "
           f"of wall clock")
    if len(timestamps) >= 2 and wall_s > 0:
        spanned_s = (timestamps[-1] - timestamps[0]).total_seconds()
        # Only worth saying when the timeline actually crosses a closed market.
        if spanned_s > len(timestamps) * BAR_INTERVAL_SEC * 1.05:
            out += (f"; spans {spanned_s / 3600:.0f}h of market time, "
                    f"so ~{spanned_s / wall_s:,.0f}x end to end "
                    f"(closed sessions cost one bar each)")
    return out


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
            ts = _parse_server_datetime(row.get("timestamp"))
            if ts is not None:
                seen.add(ts)
    return sorted(seen)


def _parse_server_datetime(raw) -> datetime | None:
    """Parse a datetime the ArenaX server put in a JSON body.

    Two formats turn up, because the server does not serialise consistently:
    hand-written handlers call .isoformat() (so "2025-09-01T09:01:00"), while
    anything handed straight to flask.jsonify comes back as an HTTP date
    ("Mon, 01 Sep 2025 09:01:00 GMT") -- that is Flask's default encoder for
    datetime, and the kbars route goes through it.

    The "GMT" is a fiction: every datetime in this codebase is a naive
    Asia/Taipei value, so the tzinfo parsedate_to_datetime attaches is dropped
    rather than converted, which would shift every bar by 8 hours.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).replace(tzinfo=None)
    except (TypeError, ValueError) as exc:
        log.warning(f"[Clock] unparseable timestamp from server: {text!r} ({exc})")
        return None


class EventHub:
    def __init__(self, account_client: AccountClient, clock,
                 on_bar_end: Callable[[datetime | None], Awaitable[None]] | None = None,
                 session_check: Callable[[], bool] | None = None):
        self.client = account_client
        self.clock = clock
        # Asked once per bar, on the live path only: "is the market open?".
        #
        # None means publish every bar, which is what replay wants and what
        # this used to do unconditionally. That mattered: a replay's bars come
        # from real trading sessions, so they are all inside market hours
        # anyway, and consulting the broker would add a fifth HTTP round trip
        # to a loop that already makes four per bar.
        #
        # It is a callable rather than a mode flag because the engine owns no
        # clock and makes no time judgements -- the broker is asked, and which
        # broker it is does not appear here.
        self.session_check = session_check
        self._market_closed = False
        self.watch_list = set()
        self.pub_socket = None
        self._last_price: dict[str, float] = {}
        self._seq: dict[str, int] = {}
        self.bars = 0
        # Called once per bar, after every symbol has been published and before
        # the clock moves. The hub does not know or care what it does; it exists
        # so order-status polling happens at a point where the server's market
        # time still matches the bar the bots were just given.
        self.on_bar_end = on_bar_end
        # Market time of the most recent bar, for anything that needs to stamp
        # an event with "now" without owning a clock.
        self.market_time: datetime | None = None

    async def _broadcast(self, snap: Snapshot):
        self._seq[snap.symbol] = self._seq.get(snap.symbol, -1) + 1
        update = PriceUpdate(seq=self._seq[snap.symbol], snapshot=snap)
        await self.pub_socket.send_multipart(
            [snap.symbol.encode('utf-8'), protocol.encode(update)]
        )
        log_feed.debug(f"[Master] Broadcasting {snap.symbol} at {snap.close} "
                       f"({snap.timestamp}, seq={update.seq})...")

    def _snapshot(self, symbol: str) -> Snapshot:
        if self.client is not None:
            return self._snapshot_real(symbol)
        return self._snapshot_mock(symbol)

    def _snapshot_real(self, symbol: str) -> Snapshot:
        # Pass the broker's Snapshot through untouched. It used to be projected
        # down to {symbol, close, timestamp}, which threw away everything else
        # and left the bot setting open=high=low=close.
        #
        # Know what survives: close and timestamp are this moment's, but open,
        # high and low are the TRADING DAY's so far -- that is what a Snapshot
        # means to shioaji and now to ArenaX too. Kbar.from_snapshot carries
        # them straight into bar.high/bar.low, so a strategy wanting per-bar
        # extremes on a 1m feed is not getting them here.
        return self.client.get_snapshots([Product(symbol=symbol)])[0]

    def _snapshot_mock(self, symbol: str) -> Snapshot:
        # Unseeded — fine for eyeballing the plumbing, but don't build a
        # reproducibility baseline on this path.
        prev = self._last_price.get(symbol, 100.0)
        price = round(max(50.0, min(200.0, prev + random.gauss(0, 1.2))), 2)
        self._last_price[symbol] = price
        return Snapshot(
            symbol=symbol, exchange=Exchange.TSE.value, timestamp=datetime.now(),
            open=prev, close=price, high=max(prev, price), low=min(prev, price),
            volume=0, average_price=round((prev + price) / 2, 2),
            action=OrderAction.BUY if price >= prev else OrderAction.SELL,
            buy_price=price, buy_volume=0, sell_price=price, sell_volume=0,
            additional_note="mock",
        )

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
            if not await self._market_is_open():
                # Hold the feed. Nothing downstream has a session of its own:
                # the hub published a bar every 60s around the clock, so a bot
                # spent the night running on_bar against the broker's cached
                # closing snapshot -- the same price, repeated, which a
                # strategy reads as a real series and can signal on.
                #
                # The whole bar is skipped, not just the publish: there is no
                # point polling orders or sampling equity on a market that has
                # not moved, and `bars` counts bars served, so it correctly
                # does not advance.
                #
                # One consequence worth knowing: a bot holding an in-flight
                # order keeps holding it until the morning, because its own
                # timeout is measured in bars and bars have stopped. It clears
                # within UNACKED_MAX_BARS of the open.
                await self.clock.sleep(BAR_INTERVAL_SEC)
                continue

            # sorted(), not list(): fixed symbol order per bar, so a multi-symbol
            # run is reproducible instead of following set iteration order.
            for symbol in sorted(self.watch_list):
                try:
                    # Blocking network I/O in real mode — keep it off the loop.
                    snap = await asyncio.to_thread(self._snapshot, symbol)
                except Exception as e:
                    log.warning(f"[Master] Snapshot fetch failed for {symbol}: {e}")
                    continue
                self.market_time = snap.timestamp
                await self._broadcast(snap)

            self.bars += 1
            if self.bars % 500 == 0:
                log.info(f"[Master] {self.bars} bars served")

            # Check resting orders here rather than in a task of its own: a
            # separate task would run on wall-clock time and could land
            # mid-step, asking the server about a bar it has already left.
            if self.on_bar_end is not None:
                await self.on_bar_end(self.market_time)

            await self.clock.sleep(BAR_INTERVAL_SEC)

        # Only reachable with ReplayClock; the live clocks never finish.
        elapsed = time.monotonic() - started
        log.info(f"[Master] Replay complete — {self.bars} bars in {elapsed:.1f}s "
                 f"({self.bars/max(elapsed, 1e-9):.0f} bars/s)")

    async def _market_is_open(self) -> bool:
        """Is the market trading? True whenever there is no check configured.

        An unanswerable check is treated as open rather than closed. Refusing
        to publish because the broker did not reply would turn a transient
        network error into a silently stalled feed; carrying on sends the loop
        into the snapshot fetch, which already handles a dead broker by logging
        and skipping the symbol.
        """
        if self.session_check is None:
            return True
        try:
            is_open = await asyncio.to_thread(self.session_check)
        except Exception as e:
            log.warning(f"[Master] could not tell whether the market is open "
                        f"({e}) — assuming it is")
            return True
        if is_open:
            if self._market_closed:
                log.info("[Master] market open — resuming the feed")
                self._market_closed = False
            return True
        if not self._market_closed:
            # Logged on the transition, not every minute: a closed market is
            # the normal state for two thirds of every weekday.
            log.info(f"[Master] market closed — holding the feed "
                     f"({self.bars} bars served so far)")
            self._market_closed = True
        return False

    def subscribe_price_feed(self, symbol: str):
        self.watch_list.add(symbol)

    def start(self, pub_socket):
        self.pub_socket = pub_socket
        return asyncio.create_task(self._reload_loop())


# ══════════════════════════════════════════════════════════════════════════════
#  ExecutionEngine — the only place that ever holds a broker session.
#
#  Note what is absent: no clock, no set_market_time, no mode check. Under
#  ReplayClock the server was already parked on bar t before the bot saw it, so
#  an order placed while handling bar t lands on a server whose mock time is t.
#  It lines up without this class knowing any of it.
#
#  Submitting an order and learning that it filled are two different events,
#  and the broker only answers the first one synchronously. place_order() comes
#  back COMMITTED_WAIT_MATCHING for anything that did not cross immediately --
#  the order is live on the server and will fill on a later bar. Reporting that
#  as REJECTED (which is what this used to do) tells the bot its cash is still
#  there while the broker has already spent it, and the two ledgers never
#  reconcile again. So resting orders are remembered and polled.
#
#  Polled, not pushed: ArenaXBrokerAPI.register_order_callback is a no-op
#  placeholder (arenax_broker_api.py:174), so there is no fill callback to
#  subscribe to. poll_open_orders() asks list_orders() -- broker-agnostic, same
#  call for sinopac -- and only when something is actually resting.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _PaperAccount:
    """Per-bot ledger for the no-broker path."""
    balance: float
    positions: dict[str, Position] = field(default_factory=dict)


class ExecutionEngine:
    def __init__(self, account_client: AccountClient | None,
                 initial_balance: float = 1_000_000.0,
                 gate: RiskGate | None = None):
        self.client = account_client
        self.initial_balance = initial_balance
        # The system's own pre-trade controls, as opposed to the broker's. The
        # broker decides whether the account can do this at all; the gate
        # decides whether this strategy should, right now.
        self.gate = gate
        self._ledger: dict[str, _PaperAccount] = {}
        # Orders the broker accepted but has not resolved: id -> (bot, order).
        # The Order is kept because a status refresh only tells us the status;
        # symbol, action, quantity and price have to come from somewhere.
        self._open: dict[str, tuple[str, Order]] = {}

    def _account_for(self, bot_id: str) -> _PaperAccount:
        return self._ledger.setdefault(bot_id, _PaperAccount(self.initial_balance))

    async def execute(self, intent: OrderIntent) -> OrderReport:
        refusal = self._refuse(intent)
        if refusal is not None:
            return refusal
        if self.client is not None:
            return await asyncio.to_thread(self._execute_via_broker, intent)
        return self._execute_paper(intent)

    def _refuse(self, intent: OrderIntent) -> OrderReport | None:
        """Ask the gate first, so a refused order costs no broker round-trip.

        Refusing here and refusing at the broker look identical to the bot --
        both arrive as a REJECTED OrderReport -- which is the point: a strategy
        should not have to know which layer said no.
        """
        if self.gate is None:
            return None
        order = intent.order
        reason = self.gate.check(intent.bot_id, order.product.symbol,
                                 order.action.value, order.quantity, order.price)
        if reason is None:
            return None
        log.warning(f"[Risk] refused {order.action.value} "
                    f"{order.product.symbol} x{order.quantity} @ {order.price} "
                    f"for {intent.bot_id}: {reason}")
        if self.client is not None:
            return self._broker_report(intent, OrderStatus.REJECTED, 0, reason)
        return self._paper_report(intent, self._account_for(intent.bot_id),
                                  OrderStatus.REJECTED, 0, reason)

    def _note_outcome(self, bot_id: str, order: Order,
                      status: OrderStatus) -> None:
        """Tell the gate an order reached a terminal state, so it can release
        the capital it was holding against that bot's allocation."""
        if self.gate is None or protocol.is_resting(status):
            return
        self.gate.record_outcome(bot_id, order.action.value,
                                 order.price * order.quantity,
                                 filled=(status == OrderStatus.FILLED))

    # ── broker path ───────────────────────────────────────────────────────────

    def _execute_via_broker(self, intent: OrderIntent) -> OrderReport:
        order = intent.order
        try:
            # place_order, not buy_stock/sell_stock: those build their own Order
            # and hand back a different id, which would make the bot's order id
            # and the broker's unrelatable. This keeps one id end to end.
            result = self.client.place_order(order)
        except Exception as e:
            return self._broker_report(intent, OrderStatus.REJECTED, 0, str(e))

        if protocol.is_resting(result.status):
            # Note the id the broker answers with, which for ArenaX is the id we
            # sent (OrderResult.linked_order), but do not assume that.
            self._open[result.linked_order or order.id] = (intent.bot_id, order)

        if self.gate is not None and result.status != OrderStatus.REJECTED:
            self.gate.record_submitted(intent.bot_id, order.product.symbol,
                                       order.action.value, order.quantity,
                                       order.price)
        self._note_outcome(intent.bot_id, order, result.status)

        return self._broker_report(intent, result.status,
                                   self._filled_qty(order, result.status),
                                   result.message)

    async def poll_open_orders(self, as_of: datetime | None) -> list[OrderReport]:
        """Reports for any resting order that has since resolved.

        `as_of` is the market time to stamp the events with; the engine holds no
        clock, so the caller — which just finished publishing a bar — says what
        time it is.
        """
        if self.client is None or not self._open:
            return []       # nothing resting, so no HTTP call

        try:
            trades = await asyncio.to_thread(self.client.list_orders)
        except Exception as e:
            log.warning(f"[Master] Could not refresh order status: {e}")
            return []

        reports = []
        for trade in trades or []:
            if trade.id not in self._open:
                continue
            status = _as_status(trade.status)
            if protocol.is_resting(status):
                continue
            bot_id, order = self._open.pop(trade.id)
            self._note_outcome(bot_id, order, status)
            reports.append(self._broker_report(
                OrderIntent(bot_id=bot_id, order=order), status,
                self._filled_qty(order, status),
                "resolved on refresh", timestamp=as_of,
            ))

        # An order we are waiting on that the broker does not list at all is
        # gone, and no further poll will ever say so. Report it rather than
        # polling it forever: the bot holds off trading that symbol until it
        # hears a verdict, so silence here is a silent trading halt.
        #
        # Only when the broker listed *something* — an empty list is more likely
        # a hiccup than every order vanishing at once.
        if trades:
            listed = {t.id for t in trades}
            for order_id in [oid for oid in self._open if oid not in listed]:
                bot_id, order = self._open.pop(order_id)
                log.warning(f"[Master] order {order_id[:8]} is no longer listed "
                            f"by the broker — reporting it as UNKNOWN")
                reports.append(self._broker_report(
                    OrderIntent(bot_id=bot_id, order=order),
                    OrderStatus.UNKNOWN, 0,
                    "broker no longer lists this order", timestamp=as_of,
                ))
        return reports

    async def cancel_open_orders(self, as_of: datetime | None,
                                 reason: str = "cancelled at shutdown") -> list[OrderReport]:
        """Pull every resting order back from the broker.

        Resting orders outlive this process. Under ReplayClock that is
        harmless -- the simulated session ends with the run -- but a paper or
        real run would walk away leaving live orders on the account.

        And a GTC order is never expired by anyone: ArenaX's ROD policy kills
        orders at the session close, GTC's deliberately does not, so an
        explicit cancel is the only thing that ever ends one.
        """
        if self.client is None or not self._open:
            return []

        reports = []
        for order_id in list(self._open):
            bot_id, order = self._open[order_id]
            try:
                result = await asyncio.to_thread(self.client.cancel_order, order_id)
            except Exception as e:
                log.warning(f"[Master] Could not cancel {order_id[:8]}: {e}")
                continue
            # Report whatever the broker said rather than assuming CANCELLED:
            # a cancel races the matcher, and "already filled" comes back as a
            # rejection of the cancel, not of the order.
            status = result.status if result else OrderStatus.UNKNOWN
            message = (result.message if result and result.message else reason)
            self._open.pop(order_id, None)
            self._note_outcome(bot_id, order, status)
            reports.append(self._broker_report(
                OrderIntent(bot_id=bot_id, order=order), status, 0, message,
                timestamp=as_of,
            ))

        if self._open:
            log.error(f"[Master] {len(self._open)} order(s) still live at the "
                      f"broker and could not be cancelled: "
                      f"{', '.join(i[:8] for i in self._open)}")
        return reports

    def _filled_qty(self, order: Order, status: OrderStatus) -> int:
        """How much of `order` is done, as far as we can tell.

        ArenaX fills whole orders at the limit price or not at all, and neither
        OrderResult nor Trade carries a filled quantity, so FILLED means all of
        it and anything else means none of it. A broker that reports partial
        fills would need a real number here, which is why PARTIAL says so out
        loud instead of quietly reporting zero.
        """
        if status == OrderStatus.FILLED:
            return order.quantity
        if status == OrderStatus.PARTIAL:
            log.warning(f"[Master] order {order.id[:8]} is PARTIAL — this engine "
                        f"cannot read a partial fill quantity, so the bot will "
                        f"be told 0 filled until the order completes")
        return 0

    def _broker_report(self, intent: OrderIntent, status: OrderStatus,
                       filled_qty: int, message: str,
                       timestamp: datetime | None = None) -> OrderReport:
        order = intent.order
        symbol = order.product.symbol
        # One sync for both numbers: get_balance() and get_positions() would
        # each run a full account sync and give two reads taken a round-trip
        # apart, which is not a state the account was ever actually in.
        state = self.client.get_account_state()
        position = next((p for p in state.positions if p.symbol == symbol), None)
        return OrderReport(
            bot_id=intent.bot_id,
            event=self._event(order, status, filled_qty, message, timestamp),
            balance=state.balance,
            position=position,
        )

    # ── paper path (no broker session) ────────────────────────────────────────

    def _execute_paper(self, intent: OrderIntent) -> OrderReport:
        acct = self._account_for(intent.bot_id)
        order = intent.order
        symbol, qty, price = order.product.symbol, order.quantity, order.price

        if order.action == OrderAction.BUY:
            if qty <= 0 or price * qty > acct.balance:
                return self._paper_report(intent, acct, OrderStatus.REJECTED, 0,
                                          "insufficient balance" if qty > 0 else "invalid qty")
            acct.balance -= price * qty
            pos = acct.positions.setdefault(symbol, Position(
                symbol=symbol, quantity=0, avg_cost=0.0,
                current_price=price, market_value=0.0,
            ))
            total = pos.quantity + qty
            pos.avg_cost = (pos.quantity * pos.avg_cost + qty * price) / total
            pos.quantity = total
        elif order.action == OrderAction.SELL:
            pos = acct.positions.get(symbol)
            if not pos or pos.quantity < qty or qty <= 0:
                return self._paper_report(intent, acct, OrderStatus.REJECTED, 0,
                                          "no/insufficient position")
            acct.balance += price * qty
            pos.quantity -= qty
            if pos.quantity == 0:
                pos.avg_cost = 0.0
        else:
            return self._paper_report(intent, acct, OrderStatus.REJECTED, 0,
                                      f"unsupported action {order.action}")

        pos = acct.positions[symbol]
        pos.current_price = price
        pos.market_value = price * pos.quantity
        pos.unrealized_pnl = (price - pos.avg_cost) * pos.quantity
        return self._paper_report(intent, acct, OrderStatus.FILLED, qty, intent.reason)

    def _paper_report(self, intent: OrderIntent, acct: _PaperAccount,
                      status: OrderStatus, filled_qty: int, message: str) -> OrderReport:
        symbol = intent.order.product.symbol
        return OrderReport(
            bot_id=intent.bot_id,
            event=self._event(intent.order, status, filled_qty, message),
            balance=acct.balance,
            position=acct.positions.get(symbol),
        )

    # ── shared ────────────────────────────────────────────────────────────────

    def _event(self, order: Order, status: OrderStatus, filled_qty: int,
               message: str, timestamp: datetime | None = None) -> OrderEvent:
        # order.created_at is the market time the broker stamped on submission
        # (arenax_broker_api.place_order overwrites it from get_market_time), so
        # it is correct under replay where datetime.now() would be years off.
        return OrderEvent(
            event_type=protocol.event_type_for(status),
            timestamp=timestamp or order.created_at,
            order_id=order.id,
            symbol=order.product.symbol,
            action=order.action,
            quantity=order.quantity,
            price=order.price,
            old_status=OrderStatus.PLACED,
            new_status=status,
            filled_quantity=filled_qty,
            filled_price=order.price if filled_qty else None,
            filled_value=order.price * filled_qty if filled_qty else None,
            message=message,
        )


def _as_status(raw) -> OrderStatus:
    """Trade.status is a plain string on the wire; widen it, don't guess."""
    try:
        return OrderStatus(raw)
    except ValueError:
        return OrderStatus.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
#  RunRecorder — keeps the one thing a report cannot be asked for afterwards.
# ══════════════════════════════════════════════════════════════════════════════

class RunRecorder:
    """Samples portfolio value per bar so the run can be reported at the end.

    Everything else a BacktestResult wants can be fetched after the fact --
    the fills from the broker, the closing balance from the account -- but what
    the portfolio was worth at bar 400 is gone the moment bar 401 starts. The
    kill switch already computes it every bar, since that is the number it
    compares against the loss limit, so this only keeps what was being thrown
    away.

    Fills come from the server rather than from the OrderReports master
    publishes: the backend applies the CostModel when it settles a fill
    (base_backend._apply_fill), so its fill_history carries the commission and
    tax that never reach master. Asking the server is the only way the report's
    cost lines have numbers in them.
    """

    def __init__(self, session_id: str, initial_balance: float,
                 journal_path: Path | None = None):
        self.session_id = session_id
        self.initial_balance = initial_balance
        # Market time of the first bar, filled in by the first observe(). Not
        # datetime.now(): under replay that is the wall clock of the machine,
        # which has nothing to do with the period being replayed.
        self.start_time: str | None = None
        self.equity_curve: list[dict] = []
        self._last_minute = ""
        # Append-only copy of the curve on disk. The pickle and the HTML are
        # written once, at the end, so anything that stops the process without
        # reaching the teardown -- a kill, an OOM, a crash in a C extension --
        # used to lose the entire run: the fills survive on the server, but the
        # equity curve exists nowhere else.
        #
        # JSONL rather than re-pickling every N bars: one line per sample is
        # O(1) per bar where a rewrite is O(n), it survives a process dying
        # mid-write with only the last line lost, and it can be read by anything.
        self._journal = None
        self.journal_path = journal_path
        if journal_path is not None:
            try:
                self._journal = open(journal_path, "a", buffering=1)
                log.info(f"[Report] equity journal → {journal_path}")
            except OSError as e:
                # A run that cannot write its journal is still a run worth
                # having; say so and carry on.
                log.warning(f"[Report] no equity journal ({e})")

    def observe(self, as_of: datetime | None, equity: float) -> None:
        """Record one equity sample, at most one per minute of market time.

        Deduped by minute to match how cjtrade_system and BacktestEngine record
        theirs, so the resampling in BacktestResult.to_returns() sees the same
        resolution whichever engine produced the curve.
        """
        stamp = as_of or datetime.now()
        if self.start_time is None:
            self.start_time = stamp.isoformat()
        minute = stamp.replace(second=0, microsecond=0).isoformat()
        if minute == self._last_minute:
            return
        self._last_minute = minute
        sample = {"time": minute, "value": round(equity, 2)}
        self.equity_curve.append(sample)
        if self._journal is not None:
            try:
                # line_buffering=1 above, so this reaches the OS on the newline.
                self._journal.write(json.dumps(sample) + "\n")
            except OSError as e:
                log.warning(f"[Report] equity journal write failed, dropping it: {e}")
                self._journal = None

    def close(self) -> None:
        """Release the journal. Safe to call twice."""
        if self._journal is not None:
            try:
                self._journal.close()
            except OSError:
                pass
            self._journal = None

    @staticmethod
    def read_journal(path: Path) -> list[dict]:
        """The curve from a journal, for rebuilding a report after a crash.

        Skips a trailing partial line rather than raising: the last write is
        exactly the one a kill interrupts.
        """
        curve = []
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    curve.append(json.loads(line))
                except ValueError:
                    log.warning(f"[Report] ignoring an incomplete journal line "
                                f"at the end of {path}")
        return curve

    def build_result(self, client: AccountClient) -> BacktestResult | None:
        """Assemble the result. Blocking HTTP — call it off the loop.

        Must run before disconnect(): the fill history lives on the server, so
        this is a read over the wire, not a look at local state.
        """
        ctrl = client.control_plane
        if ctrl is None:
            log.warning("[Report] broker has no control plane — no fills to report")
            return None
        raw = ctrl.get_backtest_state(session_id=self.session_id)
        if raw is None:
            log.warning("[Report] the server returned no fill history — no report")
            return None

        # One sync for both numbers, same reason as _broker_report: a balance
        # and a position list read a round-trip apart is not a state the
        # account was ever in.
        state = client.get_account_state()
        final_equity = state.balance + sum(p.market_value for p in state.positions)
        return BacktestResult(
            initial_balance=self.initial_balance,
            final_balance=state.balance,
            equity_curve=list(self.equity_curve),
            fill_history=raw["fill_history"],
            session_id=self.session_id,
            start_time=self.start_time,
            # cjtrade_system leaves this unset, which makes its summary report
            # uPnL as 0 and understate the total whenever the run ends holding
            # a position. Set it.
            final_equity=final_equity,
        )


def print_run_report(result: BacktestResult, open_browser: bool = True) -> None:
    """Print the summary and the round-trip table, then write the tearsheet.

    All of it comes from pkgs/analytics/evaluation/quantstats.py -- the same
    reporting layer cjtrade_system and the oneshot backtester use. Sharing it
    rather than hand-rolling a summary here is the only way a run through this
    engine and a run through those are comparable: one definition of realised
    P&L, one FIFO round-trip matcher, one annualisation factor.
    """
    report = BacktestReport(result)
    report.summary()
    report.print_round_trips()

    sid = (result.session_id or "run")[:8]
    stem = paths.reports_dir() / f"engine_{sid}"

    # Pickle first: it is the cheap one, and it is what lets you re-render a
    # report later without re-running the session.
    try:
        result.save(f"{stem}.pkl")
        log.info(f"[Report] result saved → {stem}.pkl")
    except Exception as e:
        log.warning(f"[Report] could not save the result: {e}")

    try:
        # Needs at least two equity samples to have a return series at all;
        # BacktestReport raises rather than drawing a flat line.
        report.full_report(path=f"{stem}.html", open_browser=open_browser,
                           title=f"Trading engine — {sid}")
    except Exception as e:
        log.warning(f"[Report] no HTML tearsheet ({e})")


ctx = zmq.asyncio.Context()


async def publish_report(pub_socket, report: OrderReport) -> None:
    """Send an OrderReport to its bot. Topic is the bot id."""
    log.info(f"[Master] {report.event.new_status.value} "
             f"{report.event.action.value} {report.event.symbol} "
             f"x{report.event.filled_quantity}/{report.event.quantity} "
             f"@ {report.event.price} for {report.bot_id} "
             f"({report.event.message}) balance={report.balance:.0f}")
    await pub_socket.send_multipart(
        [report.bot_id.encode('utf-8'), protocol.encode(report)]
    )


class BotRegistry:
    """What master knows about each bot, and how recently it said so.

    Master is the only process that talks to every bot, so this is the only
    place a view of "all bots" can exist. It is also how a dead or wandering
    bot gets noticed: a bot that stops reporting has either exited or is
    talking to a different master, and either way its orders should not be
    trusted.

    History is bounded. A year-long replay is ~64,000 bars per bot, and the
    point of keeping any history at all is to answer "what was it doing just
    before that", not to accumulate the run.
    """

    def __init__(self, history: int = 500):
        self._latest: dict[str, protocol.BotStatus] = {}
        self._heard_at_bar: dict[str, int] = {}
        self._reported_silent: set[str] = set()
        self.history: deque = deque(maxlen=history)

    def expect(self, bot_ids: list[str], engine_bar: int) -> None:
        """Start the silence clock for bots that have been spawned.

        Without this, silence is only ever noticed for a bot that reported at
        least once, so the case this is most meant to catch -- a bot that dies
        during startup, before its first bar -- would pass unremarked.
        """
        for bot_id in bot_ids:
            self._heard_at_bar.setdefault(bot_id, engine_bar)

    def record(self, status: protocol.BotStatus, engine_bar: int) -> None:
        self._latest[status.bot_id] = status
        self._heard_at_bar[status.bot_id] = engine_bar
        self._reported_silent.discard(status.bot_id)
        self.history.append(status)

    @property
    def latest(self) -> dict[str, protocol.BotStatus]:
        return dict(self._latest)

    def newly_silent(self, engine_bar: int, max_silent_bars: int) -> list[str]:
        """Bots that have gone quiet, each reported once rather than per bar."""
        out = []
        for bot_id, bar in self._heard_at_bar.items():
            if engine_bar - bar < max_silent_bars or bot_id in self._reported_silent:
                continue
            self._reported_silent.add(bot_id)
            out.append(bot_id)
        return out

    def summary_line(self, bot_id: str) -> str:
        s = self._latest.get(bot_id)
        if s is None:
            return f"{bot_id}: nothing heard yet"
        mon = s.monitors or {}
        keys = ("regime", "volatility", "lower_touches", "upper_touches",
                "mid_crossings", "signals_emitted")
        shown = "  ".join(f"{k}={mon[k]}" for k in keys if k in mon)
        inflight = ",".join(f"{k}:{v}" for k, v in (s.inflight or {}).items())
        return (f"{bot_id}: bar {s.bar_index} dropped={s.bars_dropped} "
                f"balance={s.balance:.0f}"
                + (f" inflight[{inflight}]" if inflight else "")
                + (f"  {shown}" if shown else "")
                + (f"\n{' ' * 10}why: {mon['last_decision']}"
                   if "last_decision" in mon else ""))


async def handle_bot_messages(pull_socket, pub_socket, engine: ExecutionEngine,
                              registry: BotRegistry, hub: "EventHub"):
    """The one reader of the PULL socket. Two message types arrive on it.

    Was handle_orders: bots now also report their own state, and it comes up
    the same socket because the alternative -- a listener per bot -- is N ports
    to secure for data master needs anyway.
    """
    log.info("[Master] Started bot message loop...")
    while True:
        try:
            msg = protocol.decode(await pull_socket.recv())
            if isinstance(msg, protocol.BotStatus):
                registry.record(msg, hub.bars)
                continue
            if isinstance(msg, OrderIntent):
                await publish_report(pub_socket, await engine.execute(msg))
                continue
            log.warning(f"[Master] ignoring unexpected message "
                        f"{type(msg).__name__} on the intent socket")
        except Exception as e:
            log.info(f"[Master] Got exception while handling a bot message: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Init task — the only place that knows which broker and which mode this is.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EngineConfig:
    """Answers from the shared form, coerced into the types the engine wants."""

    broker: str
    backend_mode: str            # ArenaX backend: backtest | paper | demo
    symbols: list[str]
    initial_balance: float
    duration_days: int
    playback_speed: float
    start_date: str | None       # None = let the server's own start date stand

    @property
    def is_live(self) -> bool:
        """paper and real track the wall clock, so no replay is possible."""
        return self.backend_mode in ("paper", "real")


def load_config(schema: Path = FORM_SCHEMA) -> EngineConfig:
    """Ask the shared form, or take answers from CLI flags when given.

    Fields whose cli_arg appears in sys.argv are never prompted (FormEngine.run
    drops them from the schema), so this is interactive by default and scriptable
    on demand:

        uv run python poc/trading_engine/main2.py \\
            --broker=arenax --mode=backtest --watch-list=0050,2317 \\
            --speed=60 --days=30 --fund=1000000 --start-date=2025-09-01
    """
    answers = FormEngine(str(schema), renderer="cli").run()

    raw_symbols = (answers.get("watch_list") or "").strip()
    symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()]

    start = (answers.get("start_date") or "").strip() or None

    def answered(key: str, default: float) -> float:
        """The answer, or the default only when there is no answer.

        `float(answers.get(key) or default)` looks equivalent and is not: 0 is
        falsy, so --speed=0 came out as the default. That matters now that 0 is
        the way to ask for an unpaced replay.
        """
        raw = answers.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return default
        return float(raw)

    return EngineConfig(
        broker=answers.get("broker", "arenax"),
        backend_mode=answers.get("mode", "backtest"),
        symbols=symbols,
        initial_balance=answered("fund", 1_000_000),
        duration_days=int(answered("days", 365)),
        playback_speed=answered("playback_speed", 1.0),
        start_date=start,
    )


def build_clock(client: AccountClient, clock: str, cfg: EngineConfig):
    """Choose the time regime. Everything downstream is broker-agnostic.

    This `if` is the entire broker/mode-specific surface. Putting sinopac here
    means returning RealtimeClock() and changing nothing else.
    """
    if clock == "realtime":
        return RealtimeClock()           # note: never touches `client`

    mw = client.control_plane            # None for a live broker
    if mw is None:
        raise RuntimeError(f"broker {client.get_broker_name()!r} has no control "
                           f"plane — clock={clock!r} needs a simulated exchange")

    if clock == "scaled":
        return ScaledClock.for_server(mw)

    if clock == "replay":
        # The form's start_date is optional. When blank, take the server's own
        # timeline origin rather than inventing one: the backtest backend has
        # already picked a start date (possibly at random) and preloaded data
        # around it, so any other guess would ask for bars that do not exist.
        start = cfg.start_date or client.get_market_time()["mock_init_time"].date().isoformat()
        end = (datetime.fromisoformat(start)
               + timedelta(days=cfg.duration_days)).date().isoformat()
        # The requested speed is honoured in every replayed mode, backtest
        # included. It used to be discarded for backtest and the replay always
        # ran flat out, so asking for 60x and asking for 30000x produced the
        # identical run and neither was the speed on the label.
        #
        # 0 means flat out, matching the "0 == no limit" this codebase already
        # uses for the status API's `limit`. There is no other sentinel: a mode
        # cannot opt out of its own setting, which is what the branch here did.
        speed = cfg.playback_speed if cfg.playback_speed > 0 else None
        return ReplayClock.for_server(mw, cfg.symbols, start, end,
                                      interval="1m", speed=speed)

    raise ValueError(f"unknown clock: {clock!r}")


async def main():
    # Ask before binding anything: the form blocks on stdin, and there is no
    # point holding sockets or a broker session open while it waits.
    cfg = await asyncio.to_thread(load_config)
    if not cfg.symbols:
        log.error("[Master] No symbols — set a watch list in the form or pass "
                  "--watch-list=0050,2317")
        return

    clock_name = "realtime" if cfg.is_live else CLOCK
    log.info(f"[Master] broker={cfg.broker} backend={cfg.backend_mode} "
             f"clock={clock_name} symbols={','.join(cfg.symbols)} "
             f"fund={cfg.initial_balance:.0f} days={cfg.duration_days}")

    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind(protocol.price_feed_address())
    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind(protocol.order_intent_address())

    account_client = AccountClient(broker_type=BrokerType.ARENAX,
                                   arenax_port=ARENAX_PORT, api_key="testkey123")
    if not await asyncio.to_thread(account_client.connect):
        log.error(f"[Master] Failed to connect to ArenaX broker (port {ARENAX_PORT}) — aborting.")
        return

    # Before spawning bots: ReplayClock does its kbar fetch and clock alignment
    # here, and there is no point feeding bots if that fails.
    try:
        clock = await asyncio.to_thread(build_clock, account_client, clock_name, cfg)
    except Exception as e:
        log.error(f"[Master] Could not build {clock_name!r} clock: {e}")
        account_client.disconnect()
        return

    # Pass the balance down: the bot keeps a local mirror for position sizing,
    # and starting it at a different number than the broker would skew every
    # decision it makes before its first order report comes back.
    #
    # The broker's balance, not cfg.initial_balance: the form's `fund` is what
    # we *asked* for, and the backend is free to have something else -- a demo
    # or paper account has whatever balance it has. Seeding from the form let
    # the bot size a 208-share order against 1,000,000 while the broker held
    # 100,000.
    bot_balance = await asyncio.to_thread(account_client.get_balance)
    if abs(bot_balance - cfg.initial_balance) > 1e-6:
        log.warning(f"[Master] broker balance is {bot_balance:.0f}, not the "
                    f"requested fund={cfg.initial_balance:.0f} — bots will size "
                    f"against the broker's number")

    # Stamped on every order the bots place, so the server tags this run's
    # fills with it and the end-of-run report can ask for exactly them. Without
    # it, a second run against a server that was not restarted would inherit
    # the first run's trades.
    session_id = uuid.uuid4().hex
    recorder = RunRecorder(
        session_id=session_id, initial_balance=bot_balance,
        journal_path=paths.reports_dir() / f"engine_{session_id[:8]}.equity.jsonl")
    bot_registry = BotRegistry(history=BOT_STATUS_HISTORY)
    # Wall clock, for the status API's uptime. Taken here rather than at the
    # top of main() so it does not count the time the form spent waiting on
    # someone to answer it.
    run_started_at = datetime.now()
    log.info(f"[Master] session {session_id}")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-u', str(BOT_C_SCRIPT), "Bot_C", str(bot_balance), session_id
    )
    await asyncio.sleep(2)       # let the subprocess finish its ZMQ connect

    # One bot today, so its allocation is the whole account and the budget
    # never bites. Add a second and each gets half, which is the point: without
    # an allocation every bot sizes against the full equity and N bots deploy
    # N times the capital.
    bots = ["Bot_C"]
    # Bar 0: bots are spawned before the hub exists, so no bar has been served.
    bot_registry.expect(bots, 0)
    gate = RiskGate(
        RiskLimits(
            max_notional_per_bot=bot_balance / len(bots),
            max_orders_per_bar=RISK_MAX_ORDERS_PER_BAR,
            max_loss_pct=RISK_MAX_LOSS_PCT,
            duplicate_window_bars=RISK_DUPLICATE_WINDOW_BARS,
        ),
        initial_equity=bot_balance,
    )
    log.info(f"[Risk] per-bot allocation {bot_balance / len(bots):,.0f}, "
             f"max {RISK_MAX_ORDERS_PER_BAR} order(s)/bar, "
             f"halt at -{RISK_MAX_LOSS_PCT:.0%}, "
             f"duplicate window {RISK_DUPLICATE_WINDOW_BARS} bar(s)")

    engine = ExecutionEngine(account_client=account_client,
                             initial_balance=cfg.initial_balance,
                             gate=gate)

    # Consecutive failed account reads. Lives out here so report_resolved_orders
    # can keep a count across bars.
    account_read_failures = 0

    async def report_resolved_orders(as_of: datetime | None) -> None:
        """Tell each bot about any of its resting orders that just resolved,
        then let the risk gate see the bar.

        Expect one bar of latency on fills: an order placed while handling bar
        t is only checked for a fill over (t, t+1], so the earliest it can be
        reported is the end of bar t+1. That is the market's behaviour, not an
        artefact -- a fill cannot be observed before the prices that caused it.
        """
        for report in await engine.poll_open_orders(as_of):
            await publish_report(pub_socket, report)

        gate.start_bar(hub.bars)

        for bot_id in bot_registry.newly_silent(hub.bars, BOT_SILENT_BARS):
            log.error(f"[Master] {bot_id} has not reported for "
                      f"{BOT_SILENT_BARS} bars — it has exited, stalled, or is "
                      f"listening to another master. Its orders are stale.")
        if hub.bars % BOT_STATUS_EVERY == 0:
            for bot_id in bots:
                log.info(f"[Bots] {bot_registry.summary_line(bot_id)}")

        # Guarded, because this used to be the most fragile line in the engine:
        # a single unanswered read ended the run. The broker going away for one
        # bar raised out of here, out of _reload_loop, out of main(), and the
        # whole run's equity curve went with it. Verified by killing the server
        # mid-run -- it died on `account_summary().get("balance")`.
        #
        # A failure is skipped rather than retried: the next bar is one more
        # attempt, sixty market seconds later, and a tight retry loop inside a
        # bar would just hold the loop while the server is down.
        nonlocal account_read_failures
        try:
            state = await asyncio.to_thread(account_client.get_account_state)
        except Exception as e:
            account_read_failures += 1
            log.warning(f"[Master] could not read the account on bar {hub.bars} "
                        f"({account_read_failures} in a row): {e}")
            # Counted in bars, not seconds, because what the number measures is
            # how many bars the bots have traded with nobody watching the
            # account -- and bars are what they trade on.
            if account_read_failures >= ACCOUNT_READ_MAX_FAILURES and not gate.halted:
                # Halt rather than carry on. The kill switch is the only thing
                # standing between a losing strategy and the whole account, and
                # it cannot see anything without this read. Refusing new orders
                # while blind is the conservative failure, and it is visible in
                # /status instead of being a gap in a log.
                gate.halt(f"the account has been unreadable for "
                          f"{account_read_failures} bars — refusing new orders "
                          f"until it can be seen again")
                log.error(f"[Risk] KILL SWITCH — {gate.halt_reason}")
                for report in await engine.cancel_open_orders(as_of, "account unreadable"):
                    await publish_report(pub_socket, report)
            return
        if account_read_failures:
            log.info(f"[Master] account readable again after "
                     f"{account_read_failures} bar(s)")
            account_read_failures = 0

        equity = state.balance + sum(p.market_value for p in state.positions)
        # Record before the gate looks at it: a bar that trips the kill switch
        # is the most interesting point on the curve, so it has to be on it.
        recorder.observe(as_of, equity)
        tripped = gate.observe_equity(equity)
        if tripped:
            # A halt that leaves working orders out there is not a halt, so pull
            # them before refusing anything new.
            log.error(f"[Risk] KILL SWITCH — {tripped}")
            for report in await engine.cancel_open_orders(as_of, "risk halt"):
                await publish_report(pub_socket, report)

    # Only the live path consults the trading session. Under replay the bars
    # themselves came from real sessions, so there is nothing to gate and the
    # check would only cost a round trip per bar.
    hub = EventHub(account_client=account_client, clock=clock,
                   on_bar_end=report_resolved_orders,
                   session_check=(account_client.is_market_open
                                  if cfg.is_live else None))
    for s in cfg.symbols:
        hub.subscribe_price_feed(s)

    asyncio.create_task(handle_bot_messages(pull_socket, pub_socket, engine,
                                            bot_registry, hub))

    # Read-only HTTP view of the run, loopback only — see status_api's module
    # docstring for why it is HTTP, why nothing here renders, and what the
    # security posture is. Started last, so everything it reads already exists.
    status_runner = await status_api.start(
        status_api.EngineView(
            session_id=session_id, started_at=run_started_at, cfg=cfg,
            clock_name=clock_name, clock=clock, hub=hub, recorder=recorder,
            registry=bot_registry, gate=gate, account_client=account_client,
            bots=bots,
        ),
        STATUS_PORT,
    )

    try:
        await hub.start(pub_socket)
    finally:
        # First, so a poller cannot catch the engine half dismantled: what
        # follows cancels orders and kills the bots, and a /status answered
        # mid-teardown would describe a run that no longer exists.
        if status_runner is not None:
            await status_runner.cleanup()

        # Before anything else: the broker still holds whatever was resting,
        # and it outlives this process.
        try:
            for report in await engine.cancel_open_orders(hub.market_time):
                await publish_report(pub_socket, report)
        except Exception as e:
            log.error(f"[Master] Shutdown cancel failed, orders may still be "
                      f"live at the broker: {e}")

        log.info("[Master] Terminating all bots...")
        try:
            proc.terminate()
            await proc.wait()
        except Exception:
            pass

        # What each bot last said. Worth printing even on a clean run: a bot
        # whose last word was 400 bars ago stopped reporting while master kept
        # going, and the fill count alone would not show that.
        for bot_id in bots:
            log.info(f"[Bots] {bot_registry.summary_line(bot_id)}")
        log.info("[Master] Trading engine terminated.")

        # After the bots are gone so the report is not interleaved with their
        # output, and before disconnect() because the fills are a server read.
        try:
            result = await asyncio.to_thread(recorder.build_result, account_client)
            if result is not None:
                print_run_report(result)
        except Exception as e:
            log.error(f"[Report] could not build the run report: {e}")

        # After the report, so a failure above still leaves the journal intact
        # on disk rather than half-flushed.
        recorder.close()
        account_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
