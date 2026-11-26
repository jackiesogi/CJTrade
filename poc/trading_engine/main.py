"""
poc/trading_engine/main.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
The trading engine's master: one broker session, a price feed to N bot
processes, and the only place orders are placed.

Each bar, master asks the broker for every watched symbol's closed 1m bars
since the last one it published (client.market.get_kbars) and publishes each
one as a Kbar. The broker decides which bars have closed -- the simulated
clock for ArenaX, the wall clock for a live broker -- so the same loop serves
a replay and a live run, and a bar is never published while it is still
forming. A minute in which a symbol did not trade has no bar, and nothing is
published for it.

Then it waits:

    await self.clock.sleep(BAR_INTERVAL_SEC)

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
                    same data are identical. The timestamps come from the
                    server's GET /api/v1/clock/timeline, because the bars
                    themselves stay hidden until the clock reaches them.

Pick one with CLOCK below.
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
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import setup_logging
from cjtrade.pkgs.models.backtest import BacktestResult
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
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

# setup_logging(LOG_LEVEL) is called at the start of main(). It also holds
# urllib3 (two DEBUG lines per HTTP call, ~10:1 against our own output in
# replay) and matplotlib/PIL (font-cache chatter right before the end-of-run
# summary) at WARNING.
log = get_logger("engine")
log_clock = get_logger("engine.clock")
log_risk = get_logger("engine.risk")
log_report = get_logger("engine.report")
log_bots = get_logger("engine.bots")

# Separate logger for the per-bar feed so it can be muted on its own: at high
# playback speed this is thousands of lines a second, which is useful when
# eyeballing one bar and useless when watching a two-month replay.
log_feed = get_logger("engine.feed")
log_feed.setLevel(FEED_LOG_LEVEL)


def _at(ts: datetime | None) -> str:
    """``"@YYYY-MM-DD HH:MM "`` for a simulated moment, to open a log message;
    empty when the moment is unknown."""
    return f"@{ts:%Y-%m-%d %H:%M} " if ts else ""

# Which bots this run spawns, and what each one trades.
#
# A bot is a strategy plus a symbol. The script decides the strategy (see
# bot_a.py, bot_b.py, bot_c.py, each of which is a few lines over
# bot_runner.run_bot); the symbol is passed on the command line, so pointing a
# strategy at a different stock does not mean editing a bot file.
#
# The symbol is spelled out here rather than left to the bot file because
# master is the only process that knows the watch list, and so the only one
# that can catch a bot assigned a symbol nobody publishes. A bot file keeps its
# own SYMBOL as the standalone default, for running it by hand without master.
#
# Only Bot_C ships enabled. The other two are one uncommented line away, and
# the line is here rather than behind a flag because turning a bot on changes
# the run in a way a flag would hide: the risk gate splits the account N ways
# (see RiskLimits.max_notional_per_bot below), so adding a bot halves what
# every existing bot may spend. Nothing about the engine stops you running all
# three -- but the numbers from a one-bot run and a three-bot run are not
# comparable, and that should be a deliberate edit.
# `extra` is appended to the bot's argv. Only bot_custom.py uses it, to say
# which strategy file to run; the three built-in bots carry their strategy in
# the script itself and take nothing.
BOT_ROSTER: list[tuple[str, str, str, tuple[str, ...]]] = [
    # (bot_id, script, symbol, extra argv)
    # ("Bot_C", "bot_c.py", "2317", ()),     # Bollinger mean reversion
    # ("Bot_A", "bot_a.py", "0050", ()),   # monthly DCA, never sells
    ("Bot_B", "bot_b.py", "2357", ()),   # ADX regime switch
    # A strategy somebody wrote, loaded from a file. See bot_custom.py and
    # cjtrade.pkgs.strategy.authoring.
    # ("Bot_U", "bot_custom.py", "2317", ("/path/to/strategy.py",)),
]
BOT_DIR = Path(__file__).resolve().parent

# Where a caller can hand in a roster instead of using the one above.
#
#     --roster=/path/to/roster.json
#
#     [{"bot_id": "Bot_U1", "script": "bot_custom.py", "symbol": "2317",
#       "extra": ["/path/to/strategy.py"]}]
#
# A file rather than a flag per bot, because N bots in one flag is a quoting
# problem and a roster is structured anyway. Read straight from argv rather
# than through the form: the form asks a person questions, and this is one
# process telling another what to run.
ROSTER_FLAG = "--roster="


def roster_from_argv(argv: list[str] | None = None) -> list[tuple] | None:
    """The roster `--roster=` points at, or None to use BOT_ROSTER.

    Raises on a file that exists but cannot be used. A caller that asked for a
    specific set of bots and silently got the default instead would be the
    worst outcome here -- it would look like a successful run of the wrong
    thing.
    """
    args = sys.argv if argv is None else argv
    path = next((a[len(ROSTER_FLAG):] for a in args
                 if a.startswith(ROSTER_FLAG)), None)
    if not path:
        return None

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} must hold a non-empty list of bots")

    out: list[tuple] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}[{i}] is not an object")
        try:
            bot_id = str(entry["bot_id"])
            script = str(entry["script"])
            symbol = str(entry["symbol"])
        except KeyError as missing:
            raise ValueError(f"{path}[{i}] has no {missing}") from None
        if bot_id in seen:
            # Two bots on one id would share a PUB topic, so each would act on
            # the other's order reports.
            raise ValueError(f"{path} lists {bot_id!r} twice")
        seen.add(bot_id)
        # The script must be one of ours. A roster is written by another
        # process, and "run this file" with an arbitrary path would make the
        # roster a way to execute anything -- the strategy file is the thing
        # that is allowed to be arbitrary, and it is data to bot_custom rather
        # than the program being run.
        if script not in {p.name for p in BOT_DIR.glob("bot_*.py")}:
            raise ValueError(f"{path}[{i}] names {script!r}, which is not a "
                             f"bot script in {BOT_DIR}")
        extra = tuple(str(x) for x in (entry.get("extra") or ()))
        out.append((bot_id, script, symbol, extra))
    return out

ARENAX_PORT = 8802
BAR_INTERVAL_SEC = 60        # market seconds between polls == 1m bars

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
# Before bar 0: how long to wait for every spawned bot to prove it is
# subscribed. Under replay, after each bar: how long to wait for every bot to
# answer it before stepping on without the ones that did not.
BOT_HANDSHAKE_TIMEOUT_S = 30.0
BAR_BARRIER_TIMEOUT_S = 30.0

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
        log_clock.info("scaled: server playback_speed=%sx", speed)
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
            log_clock.warning(
                "behind by %.0fms (~%.1f bars skipped): cycle exceeds %.1fms "
                "budget at playback_speed=%sx",
                -slack * 1000, skipped, wall * 1000, self.speed)
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
            log_clock.warning(
                "@%s cannot keep up with %gx: %d bar(s) late, worst %.0fms vs "
                "%.1fms budget; running flat out, slower than requested",
                f"{self.now:%Y-%m-%d %H:%M}", self.speed, self._behind_bars,
                self._behind_worst_ms, wall * 1000)
            self._behind_bars = 0
            self._behind_worst_ms = 0.0
        self._deadline = time.monotonic()      # re-baseline, don't accrue debt

    @classmethod
    def for_server(cls, mw, symbols, start, end, interval="1m", speed=None) -> "ReplayClock":
        if not hasattr(mw, "set_market_time"):
            raise RuntimeError(
                "ArenaXMiddleWare.set_market_time() is missing — ReplayClock cannot "
                "step the server clock without it. Use CLOCK='scaled' instead."
            )

        if not hasattr(mw, "get_timeline"):
            raise RuntimeError("ArenaXMiddleWare.get_timeline() is missing — "
                               "ReplayClock cannot find the bars to step to.")
        timestamps = _bar_timestamps(mw, symbols, start, end, interval)
        if not timestamps:
            raise ValueError(f"ArenaX has no bars for {symbols} in [{start}, {end})")

        # Set ArenaX server time.
        mw.set_timeline_origin(mock_init_time=timestamps[0].isoformat(),
                           auto_start_progress=False, auto_preload_data=False)

        # After set_timeline_origin, because that is the call that moves the
        # server's start_date, and its price window is measured from it.
        _assert_server_data_covers(mw, timestamps)

        log_clock.info("replay: %d bars, %s .. %s, %s", len(timestamps),
                       timestamps[0], timestamps[-1],
                       _pace_summary(timestamps, speed))
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
    """Union of every symbol's bar timestamps in ``[start, end)``, sorted.

    Union, not intersection: a symbol halted for a day should not delete that day
    from everyone else's timeline.

    Asked of the server's timeline route rather than read off the bars: the
    kbars route only returns bars the server clock has already reached, and
    the timeline is needed before the replay starts.
    """
    return mw.get_timeline(list(symbols), start, end, interval)


def _assert_server_data_covers(mw, timestamps: list[datetime]) -> None:
    """Refuse to replay past the end of the server's price data.

    The two ranges are built independently: the engine replays
    `start + --days`, the server loads `start_date + AX_BACKTEST_DURATION_DAYS`
    from its own .cjsys, and nothing passes --days along. When the engine's is
    larger the overrun is silent: the server matches orders and prices
    positions against the bars it preloaded, and past their end it keeps
    using the last one. Session 738a640c, back when the feed was snapshots,
    replayed 365 days against a 300-day server and broadcast an unchanged
    709.0 for its final 11,799 bars, which the strategy read as a
    zero-volatility market and the tearsheet priced a held position at.

    Raises rather than warns: a warning lets the run finish and write a report
    that looks like any other, with the flat tail findable only by hand.
    """
    cfg = mw.get_config()
    days = (cfg or {}).get("internal_config", {}).get("backtest_duration_days")
    if not isinstance(days, int):
        # Not evidence of a mismatch, so not fatal -- but say the check was
        # skipped rather than pass silently.
        log_clock.warning("server did not report backtest_duration_days; "
                          "cannot verify it covers the replay")
        return

    # Mirrors the server: set_historical_time_abs snaps start_date to 09:00,
    # create_historical_market loads start_date + days_preload.
    server_end = timestamps[0].replace(hour=9, minute=0, second=0,
                                       microsecond=0) + timedelta(days=days)
    if timestamps[-1] <= server_end:
        log_clock.info("server holds %d day(s) of prices %s..%s, covers replay",
                       days, f"{timestamps[0]:%Y-%m-%d}",
                       f"{server_end:%Y-%m-%d}")
        return

    needed = (timestamps[-1] - timestamps[0]).days + 1
    raise RuntimeError(
        f"the server holds {days} day(s) of prices from "
        f"{timestamps[0]:%Y-%m-%d}, ending {server_end:%Y-%m-%d}, but this "
        f"replay runs to {timestamps[-1]:%Y-%m-%d} — "
        f"{(timestamps[-1] - server_end).days} day(s) past it. Every bar past "
        f"the server's end would silently repeat its last price.\n"
        f"Fix either side:\n"
        f"  - replay less: --days={days} or lower, or\n"
        f"  - load more: AX_BACKTEST_DURATION_DAYS={needed} (env, or "
        f"src/cjtrade/apps/ArenaX/configs/<mode>.cjsys) and RESTART the "
        f"server — it reads that only at startup."
    )


class EventHub:
    def __init__(self, account_client: AccountClient, clock,
                 on_bar_end: Callable[[datetime | None], Awaitable[None]] | None = None,
                 session_check: Callable[[], bool] | None = None,
                 after_publish: Callable[[dict[str, int]], Awaitable[None]] | None = None):
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
        # Timestamp of the last bar published per symbol. The next request
        # starts after it, so a bar that arrives late is published one round
        # later rather than lost, and none is published twice.
        self._last_bar: dict[str, datetime] = {}
        self.bars = 0
        # Called once per bar, after every symbol has been published and before
        # the clock moves. The hub does not know or care what it does; it exists
        # so order-status polling happens at a point where the server's market
        # time still matches the bar the bots were just given.
        self.on_bar_end = on_bar_end
        # Called once per bar right after the publish, with each symbol's seq.
        # Replay uses it to wait until every bot has answered the bar, so the
        # bots' orders are placed before the clock moves and not whenever
        # their process happens to get scheduled. None on the live path,
        # where the market does not wait for anyone.
        self.after_publish = after_publish
        # Market time of the most recent bar, for anything that needs to stamp
        # an event with "now" without owning a clock.
        self.market_time: datetime | None = None

    async def _broadcast(self, bar: Kbar):
        self._seq[bar.symbol] = self._seq.get(bar.symbol, -1) + 1
        update = PriceUpdate(seq=self._seq[bar.symbol], bar=bar)
        await self.pub_socket.send_multipart(
            [bar.symbol.encode('utf-8'), protocol.encode(update)]
        )
        log_feed.debug("@%s %s O=%s H=%s L=%s C=%s V=%s seq=%d",
                       f"{bar.timestamp:%Y-%m-%d %H:%M}", bar.symbol, bar.open,
                       bar.high, bar.low, bar.close, bar.volume, update.seq)

    def _market_now(self) -> datetime:
        """Market time this round. The replay clock's own when it has one.

        Otherwise the broker's: a scaled ArenaX clock runs on its own, and a
        live broker answers with the wall clock. One round trip per bar.
        """
        now = getattr(self.clock, "now", None)
        if isinstance(now, datetime):
            return now
        if self.client is None:
            return datetime.now()
        return self.client.get_market_time()["mock_current_time"]

    def _new_bars(self, symbol: str, now: datetime) -> list[Kbar]:
        """The symbol's closed 1m bars after the last one published.

        The window ends past `now` on purpose: which bars have closed is the
        broker's call (MarketData.get_kbars returns closed bars only), so the
        engine never needs to agree with the broker to the second. On the
        first round it reaches back just under one bar, so the run starts
        with the bar that closed at `now` and not with the day's history.
        """
        if self.client is None:
            return [self._bar_mock(symbol, now)]
        last = self._last_bar.get(symbol)
        start = (last + timedelta(seconds=1) if last is not None
                 else now - timedelta(seconds=BAR_INTERVAL_SEC - 1))
        bars = self.client.market.get_kbars(
            symbol, start, now + timedelta(seconds=BAR_INTERVAL_SEC), "1m")
        return [b for b in bars if last is None or b.timestamp > last]

    def _bar_mock(self, symbol: str, now: datetime) -> Kbar:
        # Unseeded — fine for eyeballing the plumbing, but don't build a
        # reproducibility baseline on this path.
        prev = self._last_price.get(symbol, 100.0)
        price = round(max(50.0, min(200.0, prev + random.gauss(0, 1.2))), 2)
        self._last_price[symbol] = price
        return Kbar(timestamp=now.replace(second=0, microsecond=0), open=prev,
                    high=max(prev, price), low=min(prev, price), close=price,
                    volume=0, symbol=symbol)

    async def _reload_loop(self):
        """Publish every watched symbol's new closed bars, wait one bar, repeat.

        `self.clock.sleep(60)` waits 60 seconds of MARKET time. Under
        RealtimeClock that is 60 real seconds; under ScaledClock it is
        60/speed; under ReplayClock it costs nothing at all and just steps to
        the next bar. Same line either way -- that is the only reason this loop
        needs no mode branch.
        """
        started = time.monotonic()
        while not self.clock.finished:
            # Read before _market_is_open(), which clears it on the flip.
            was_closed = self._market_closed
            if not await self._market_is_open():
                # Hold the feed. Nothing downstream has a session of its own:
                # when the feed was snapshots the hub published one every 60s
                # around the clock, so a bot spent the night running on_bar
                # against the broker's cached closing snapshot -- the same
                # price, repeated, which a strategy reads as a real series and
                # can signal on. A closed market has no new bars either, so
                # skipping the round now mostly saves the requests.
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
                #
                # Said out loud rather than simply held. A bot reads silence as
                # a dead master and exits -- correctly, because it cannot tell
                # the difference and acting on a stale mirror is worse. In a
                # real paper run that cost the whole session: the bot started
                # at 01:46, this branch held the feed, and the bot gave up 185s
                # later. Seven hours on, 169 bars went out to nobody.
                await self._publish_feed_status(False, "market closed")
                await self.clock.sleep(BAR_INTERVAL_SEC)
                continue

            if was_closed:
                # One message on the way back, so a bot's log shows the gap
                # ending rather than just bars reappearing.
                await self._publish_feed_status(True, "market open")

            try:
                now = await asyncio.to_thread(self._market_now)
            except Exception as e:
                log.warning("market time read failed (%s), skipping bar", e)
                await self.clock.sleep(BAR_INTERVAL_SEC)
                continue
            self.market_time = now

            # sorted(), not list(): fixed symbol order per bar, so a multi-symbol
            # run is reproducible instead of following set iteration order.
            quiet: list[str] = []
            for symbol in sorted(self.watch_list):
                try:
                    # Blocking network I/O — keep it off the loop.
                    bars = await asyncio.to_thread(self._new_bars, symbol, now)
                except Exception as e:
                    # Nothing is lost: the next round asks again from the last
                    # bar that was published.
                    log.warning("@%s kbars %s failed: %s",
                                f"{now:%Y-%m-%d %H:%M}", symbol, e)
                    continue
                if not bars:
                    quiet.append(symbol)
                    continue
                for bar in bars:
                    await self._broadcast(bar)
                self._last_bar[symbol] = bars[-1].timestamp

            if quiet:
                # A symbol that did not trade this minute has no bar, so its
                # bots hear nothing. Say why, or a bot on a thinly traded
                # stock reads a few quiet minutes as a dead master and exits.
                await self._publish_feed_status(
                    True, f"no trade this bar: {','.join(quiet)}")

            if self.after_publish is not None:
                await self.after_publish(dict(self._seq))

            self.bars += 1
            if self.bars % 500 == 0:
                log.info("@%s %d bars served",
                         f"{self.market_time:%Y-%m-%d %H:%M}", self.bars)

            # Check resting orders here rather than in a task of its own: a
            # separate task would run on wall-clock time and could land
            # mid-step, asking the server about a bar it has already left.
            if self.on_bar_end is not None:
                await self.on_bar_end(self.market_time)

            await self.clock.sleep(BAR_INTERVAL_SEC)

        # Only reachable with ReplayClock; the live clocks never finish.
        elapsed = time.monotonic() - started
        log.info("replay done: %d bars in %.1fs (%.0f bars/s)", self.bars,
                 elapsed, self.bars / max(elapsed, 1e-9))

    async def _publish_feed_status(self, market_open: bool, reason: str) -> None:
        """Tell every bot why the feed looks the way it does.

        On its own topic, so master does not have to know which bots exist --
        the same reason PriceUpdate goes out on the symbol rather than per
        subscriber.
        """
        if self.pub_socket is None:
            return
        await self.pub_socket.send_multipart([
            protocol.FEED_STATUS_TOPIC.encode('utf-8'),
            protocol.encode(protocol.FeedStatus(
                market_open=market_open, reason=reason,
                bars_served=self.bars, sent_at=datetime.now())),
        ])

    async def _market_is_open(self) -> bool:
        """Is the market trading? True whenever there is no check configured.

        An unanswerable check is treated as open rather than closed. Refusing
        to publish because the broker did not reply would turn a transient
        network error into a silently stalled feed; carrying on sends the loop
        into the kbar fetch, which already handles a dead broker by logging
        and skipping the symbol.
        """
        if self.session_check is None:
            return True
        try:
            is_open = await asyncio.to_thread(self.session_check)
        except Exception as e:
            log.warning("market-open check failed (%s), assuming open", e)
            return True
        if is_open:
            if self._market_closed:
                log.info("market open, resuming feed")
                self._market_closed = False
            return True
        if not self._market_closed:
            # Logged on the transition, not every minute: a closed market is
            # the normal state for two thirds of every weekday.
            log.info("market closed, holding feed (%d bars served)", self.bars)
            self._market_closed = True
        return False

    def seq_of(self, symbol: str) -> int:
        """Seq of the last bar published for `symbol`; -1 before the first."""
        return self._seq.get(symbol, -1)

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
        log_risk.warning("%srefused %s %s x%d px=%s for %s: %s",
                         _at(order.created_at), order.action.value,
                         order.product.symbol, order.quantity, order.price,
                         intent.bot_id, reason)
        if self.client is not None:
            return self._broker_report(intent, OrderStatus.REJECTED, 0, reason)
        return self._paper_report(intent, self._account_for(intent.bot_id),
                                  OrderStatus.REJECTED, 0, reason)

    def _note_outcome(self, order_id: str, status: OrderStatus) -> None:
        """Tell the gate an order reached a terminal state, so it can release
        the capital it was holding against that bot's allocation.

        By order id, so the gate ignores what it never recorded (an order the
        broker rejected on placement) and counts each order only once."""
        if self.gate is None or protocol.is_resting(status):
            return
        self.gate.record_outcome(order_id, filled=(status == OrderStatus.FILLED))

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

        # The id the broker answers with, which for ArenaX is the id we sent
        # (OrderResult.linked_order), but do not assume that.
        order_id = result.linked_order or order.id
        if protocol.is_resting(result.status):
            self._open[order_id] = (intent.bot_id, order)

        if self.gate is not None and result.status != OrderStatus.REJECTED:
            self.gate.record_submitted(intent.bot_id, order.product.symbol,
                                       order.action.value, order.quantity,
                                       order.price, order_id=order_id)
        self._note_outcome(order_id, result.status)

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
            log.warning("%sorder status refresh failed: %s", _at(as_of), e)
            return []

        reports = []
        for trade in trades or []:
            if trade.id not in self._open:
                continue
            status = _as_status(trade.status)
            if protocol.is_resting(status):
                continue
            bot_id, order = self._open.pop(trade.id)
            self._note_outcome(trade.id, status)
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
                log.warning("%sorder %s no longer listed by broker, "
                            "reporting UNKNOWN", _at(as_of), order_id[:8])
                reports.append(self._broker_report(
                    OrderIntent(bot_id=bot_id, order=order),
                    OrderStatus.UNKNOWN, 0,
                    "broker no longer lists this order", timestamp=as_of,
                ))
        return reports

    async def cancel_open_orders(self, as_of: datetime | None,
                                 reason: str = "cancelled at shutdown",
                                 only_bot: str | None = None) -> list[OrderReport]:
        """Pull resting orders back from the broker. All of them, or one bot's.

        `only_bot` is for stopping a single bot mid-run: its resting orders
        have to come back, because once the bot is gone nothing is mirroring
        the reports and an order that fills later would move the account with
        no strategy aware of it.

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
            if only_bot is not None and bot_id != only_bot:
                continue
            try:
                result = await asyncio.to_thread(self.client.cancel_order, order_id)
            except Exception as e:
                log.warning("%scancel %s failed: %s", _at(as_of),
                            order_id[:8], e)
                continue
            # Report whatever the broker said rather than assuming CANCELLED:
            # a cancel races the matcher, and "already filled" comes back as a
            # rejection of the cancel, not of the order.
            status = result.status if result else OrderStatus.UNKNOWN
            message = (result.message if result and result.message else reason)
            self._open.pop(order_id, None)
            # Only an outcome the cancel establishes. A refused cancel usually
            # means the order filled first, so releasing its capital here would
            # hand the bot money it has already spent; it stays counted.
            if status in (OrderStatus.CANCELLED, OrderStatus.FILLED):
                self._note_outcome(order_id, status)
            else:
                log.warning("%scancel %s answered %s; capital stays reserved",
                            _at(as_of), order_id[:8], status.value)
            reports.append(self._broker_report(
                OrderIntent(bot_id=bot_id, order=order), status, 0, message,
                timestamp=as_of,
            ))

        # Scoped to what this call was asked to cancel. Unscoped, stopping one
        # bot would report every other bot's live orders as a failure.
        leftover = [oid for oid, (bid, _) in self._open.items()
                    if only_bot is None or bid == only_bot]
        if leftover:
            log.error("%s%d order(s) still live at broker, cancel failed: %s",
                      _at(as_of), len(leftover),
                      ", ".join(i[:8] for i in leftover))
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
            log.warning("%sorder %s PARTIAL: fill qty unreadable, bot told 0 "
                        "filled until it completes", _at(order.created_at),
                        order.id[:8])
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
                log_report.info("equity journal: %s", journal_path)
            except OSError as e:
                # A run that cannot write its journal is still a run worth
                # having; say so and carry on.
                log_report.warning("no equity journal: %s", e)

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
                log_report.warning("%sequity journal write failed, dropping "
                                   "it: %s", _at(stamp), e)
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
                    log_report.warning("ignoring incomplete last journal line "
                                       "in %s", path)
        return curve

    def build_result(self, client: AccountClient) -> BacktestResult | None:
        """Assemble the result. Blocking HTTP — call it off the loop.

        Must run before disconnect(): the fill history lives on the server, so
        this is a read over the wire, not a look at local state.
        """
        ctrl = client.control_plane
        if ctrl is None:
            log_report.warning("broker has no control plane, no fills to report")
            return None
        raw = ctrl.get_backtest_state(session_id=self.session_id)
        if raw is None:
            log_report.warning("server returned no fill history, no report")
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
        log_report.info("result saved: %s.pkl", stem)
    except Exception as e:
        log_report.warning("result save failed: %s", e)

    try:
        # Needs at least two equity samples to have a return series at all;
        # BacktestReport raises rather than drawing a flat line.
        report.full_report(path=f"{stem}.html", open_browser=open_browser,
                           title=f"Trading engine — {sid}")
    except Exception as e:
        log_report.warning("no HTML tearsheet: %s", e)


ctx = zmq.asyncio.Context()


async def publish_report(pub_socket, report: OrderReport) -> None:
    """Send an OrderReport to its bot. Topic is the bot id."""
    ev = report.event
    log.info("%s%s %s %s x%d/%d px=%s for %s (%s) balance=%.0f",
             _at(ev.timestamp), ev.new_status.value, ev.action.value,
             ev.symbol, ev.filled_quantity, ev.quantity, ev.price,
             report.bot_id, ev.message, report.balance)
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
        # Bots master told to stop, and why. They stay in `latest` and in the
        # status API's bot list: a bot that was switched off should still show
        # its last state and say that it was switched off, not disappear and
        # not be reported as stalled.
        self._stopped: dict[str, str] = {}
        self.history: deque = deque(maxlen=history)
        # The last PriceUpdate.seq each bot has reported, and a wake-up for
        # anything waiting on one. See wait_for().
        self._seq: dict[str, int] = {}
        self._changed = asyncio.Event()

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
        self._seq[status.bot_id] = status.seq
        # A startup handshake carries no bar, so it is not part of the run.
        if status.market_time is not None:
            self.history.append(status)
        self._changed.set()

    def heard_from(self) -> set[str]:
        return set(self._seq)

    def behind(self, wanted: dict[str, int]) -> list[str]:
        """Bots that have not yet reported the seq `wanted` asks of them."""
        return [b for b, seq in wanted.items()
                if b not in self._stopped and self._seq.get(b, -2) < seq]

    def excuse_caught_up(self, wanted: dict[str, int], engine_bar: int) -> None:
        """Count bots that have answered every bar they were sent as heard from.

        A bot only reports when its symbol has a bar, and a symbol that does
        not trade for a while has none. That bot is waiting, not silent, so
        it must not trip newly_silent. A bot that never answered at all is
        still behind (its seq is unknown) and stays on the clock.
        """
        for bot_id, seq in wanted.items():
            if not self.behind({bot_id: seq}):
                self._heard_at_bar[bot_id] = engine_bar

    async def wait_for(self, done, timeout: float) -> bool:
        """Wait until done() is true or `timeout` seconds pass.

        record() runs on the same event loop, so checking done() after
        clearing the event cannot miss a report that arrives in between.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            self._changed.clear()
            if done():
                return True
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except asyncio.TimeoutError:
                return done()
        return True

    @property
    def latest(self) -> dict[str, protocol.BotStatus]:
        return dict(self._latest)

    def mark_stopped(self, bot_id: str, reason: str) -> None:
        """Record that this bot was told to stop, so its silence is expected."""
        self._stopped[bot_id] = reason

    def is_stopped(self, bot_id: str) -> bool:
        return bot_id in self._stopped

    def stop_reason(self, bot_id: str) -> str | None:
        return self._stopped.get(bot_id)

    @property
    def stopped(self) -> dict[str, str]:
        return dict(self._stopped)

    def newly_silent(self, engine_bar: int, max_silent_bars: int) -> list[str]:
        """Bots that have gone quiet, each reported once rather than per bar.

        A bot master stopped on purpose is not silent in the sense this is
        looking for. Without the exclusion, switching one off would log "it has
        exited, stalled, or is listening to another master. Its orders are
        stale." once per run -- an alarm about the thing the operator just
        asked for, which is how people learn to ignore alarms.
        """
        out = []
        for bot_id, bar in self._heard_at_bar.items():
            if (engine_bar - bar < max_silent_bars
                    or bot_id in self._reported_silent
                    or bot_id in self._stopped):
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


async def await_bots(pub_socket, pull_socket, registry: "BotRegistry",
                     bot_ids: list[str], timeout: float) -> list[str]:
    """Wait for every bot to hear the feed, before any bar is published.

    PUB/SUB drops what is published before a subscriber has joined, so a
    bot slower to start than a fixed sleep missed the first bars with
    nothing to show for it. Master publishes FEED_SYNC_REASON until every
    bot has answered with a BotStatus. Returns the bots that never did.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    waiting = set(bot_ids)
    while waiting and loop.time() < deadline:
        await pub_socket.send_multipart([
            protocol.FEED_STATUS_TOPIC.encode('utf-8'),
            protocol.encode(protocol.FeedStatus(
                market_open=True, reason=protocol.FEED_SYNC_REASON,
                bars_served=0, sent_at=datetime.now())),
        ])
        # Read the intent socket directly: the message loop has not started,
        # and before bar 0 a bot has nothing else to send.
        while await pull_socket.poll(timeout=100):
            msg = protocol.decode(await pull_socket.recv())
            if isinstance(msg, protocol.BotStatus):
                registry.record(msg, 0)
                waiting.discard(msg.bot_id)
            else:
                log.warning("ignoring %s from a bot before the first bar",
                            type(msg).__name__)
    if not waiting:
        log.info("all %d bot(s) listening", len(bot_ids))
    return sorted(waiting)


async def handle_bot_messages(pull_socket, pub_socket, engine: ExecutionEngine,
                              registry: BotRegistry, hub: "EventHub"):
    """The one reader of the PULL socket. Two message types arrive on it.

    Was handle_orders: bots now also report their own state, and it comes up
    the same socket because the alternative -- a listener per bot -- is N ports
    to secure for data master needs anyway.
    """
    log.info("bot msg loop started")
    while True:
        try:
            msg = protocol.decode(await pull_socket.recv())
            if isinstance(msg, protocol.BotStatus):
                registry.record(msg, hub.bars)
                continue
            if isinstance(msg, OrderIntent):
                await publish_report(pub_socket, await engine.execute(msg))
                continue
            log.warning("%signoring unexpected msg %s on intent socket",
                        _at(hub.market_time), type(msg).__name__)
        except Exception as e:
            log.info("%sbot msg handling failed: %s", _at(hub.market_time), e)


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

        uv run python poc/trading_engine/main.py \\
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
        # Half-open, [start, end): --days=30 from 09-01 replays through 09-30
        # and stops before 10-01, the same window the server's
        # backtest_duration_days describes. The kbars route this used to read
        # took the end date inclusively, so a run ending on a trading day
        # also asked for that day and failed _assert_server_data_covers.
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
    setup_logging(LOG_LEVEL)
    # Ask before binding anything: the form blocks on stdin, and there is no
    # point holding sockets or a broker session open while it waits.
    cfg = await asyncio.to_thread(load_config)
    if not cfg.symbols:
        log.error("no symbols: set a watch list in the form or pass "
                  "--watch-list=0050,2317")
        return

    clock_name = "realtime" if cfg.is_live else CLOCK
    log.info("broker=%s backend=%s clock=%s symbols=%s fund=%.0f days=%d",
             cfg.broker, cfg.backend_mode, clock_name, ",".join(cfg.symbols),
             cfg.initial_balance, cfg.duration_days)

    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind(protocol.price_feed_address())
    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind(protocol.order_intent_address())

    account_client = AccountClient(broker_type=BrokerType.ARENAX,
                                   arenax_port=ARENAX_PORT, api_key="testkey123")
    if not await asyncio.to_thread(account_client.connect):
        log.error("ArenaX broker conn failed (port %s), aborting", ARENAX_PORT)
        return

    # Before spawning bots: ReplayClock does its kbar fetch and clock alignment
    # here, and there is no point feeding bots if that fails.
    try:
        clock = await asyncio.to_thread(build_clock, account_client, clock_name, cfg)
    except Exception as e:
        log.error("build %r clock failed: %s", clock_name, e)
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
        log.warning("broker balance %.0f != requested fund=%.0f; bots size "
                    "against the broker's", bot_balance, cfg.initial_balance)

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
    log.info("session %s", session_id)

    # A bot whose symbol is not in the watch list would subscribe to a topic
    # master never publishes, sit there until SILENCE_LIMIT_S and exit -- which
    # in the log looks like a crash rather than a misconfiguration. Say so
    # instead, before spawning anything.
    try:
        roster = roster_from_argv() or BOT_ROSTER
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Aborted rather than falling back: a caller that asked for a specific
        # set of bots and silently got the built-in default would be a
        # successful run of the wrong thing.
        log.error("--roster unreadable: %s", exc)
        account_client.disconnect()
        return
    if roster is not BOT_ROSTER:
        log.info("roster from --roster: %s",
                 ", ".join(f"{b}({s})" for b, _, s, _ in roster))

    procs: list[asyncio.subprocess.Process] = []
    bots: list[str] = []
    bot_symbols: dict[str, str] = {}
    for bot_id, script, symbol, extra in roster:
        if symbol not in cfg.symbols:
            log.error("%s not started: its sym %s is not in the watch list "
                      "(%s), it would never get a bar", bot_id, symbol,
                      ",".join(cfg.symbols))
            continue
        procs.append(await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(BOT_DIR / script),
            bot_id, str(bot_balance), session_id, symbol, *extra))
        bots.append(bot_id)
        bot_symbols[bot_id] = symbol
        log.info("spawned %s (%s, %s%s)", bot_id, script, symbol,
                 f", {' '.join(extra)}" if extra else "")
    if not bots:
        wanted = sorted({sym for _b, _s, sym, _e in roster})
        log.error("no bots started, aborting: roster trades %s, none in the "
                  "watch list (%s)", ",".join(wanted), ",".join(cfg.symbols))
        account_client.disconnect()
        return
    missing = await await_bots(pub_socket, pull_socket, bot_registry, bots,
                               BOT_HANDSHAKE_TIMEOUT_S)
    if missing:
        log.error("%s no answer within %.0fs: may miss the first bars, "
                  "replay not reproducible", ",".join(missing),
                  BOT_HANDSHAKE_TIMEOUT_S)

    # Each bot's allocation is the account divided by the bots that started.
    # With one bot that is the whole account and the budget never bites; with
    # three each gets a third, which is the point: without an allocation every
    # bot sizes against the full equity and N bots deploy N times the capital.
    #
    # Divided by what actually started, not by what the roster asked for, so a
    # bot skipped for a symbol nobody publishes does not quietly hold back a
    # share of the account nothing can spend.
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
    log_risk.info("per-bot allocation %s, max %d order(s)/bar, halt at -%s, "
                  "duplicate window %d bar(s)", f"{bot_balance / len(bots):,.0f}",
                  RISK_MAX_ORDERS_PER_BAR, f"{RISK_MAX_LOSS_PCT:.0%}",
                  RISK_DUPLICATE_WINDOW_BARS)

    engine = ExecutionEngine(account_client=account_client,
                             initial_balance=cfg.initial_balance,
                             gate=gate)

    async def stop_bot(bot_id: str, reason: str) -> dict:
        """Stop one bot without ending the run. The engine's only write path.

        Three things have to happen, in this order:

        1. Mark it stopped, BEFORE the command goes out. A status report
           already in flight would otherwise arrive and clear the mark.
        2. Tell the bot, on its own topic. It leaves its loop through the same
           shutdown path as any other exit, so on_end runs and its final state
           is still reported.
        3. Cancel its resting orders. Once the bot is gone nothing mirrors the
           reports, so an order that fills later would move the account with no
           strategy aware of it.

        Two things deliberately do NOT happen:

        * The position is not flattened. Stopping a strategy and liquidating
          what it holds are different decisions, and the second one sells at
          whatever price happens to be there. Whoever wants that has to ask
          for it.
        * The other bots' risk budget is not widened. `max_notional_per_bot`
          was divided by the roster at startup and it stays that way --
          quietly giving the survivors more room because somebody switched a
          bot off is the opposite of what pressing that button means.
        """
        if bot_id not in bots:
            return {"ok": False,
                    "error": f"no bot {bot_id!r} in this run",
                    "bots": list(bots)}

        if bot_registry.is_stopped(bot_id):
            # Idempotent: pressing it twice is the same as pressing it once,
            # which matters because the first press may have looked like it
            # did nothing while the bot finished its bar.
            return {"ok": True, "bot_id": bot_id, "already_stopped": True,
                    "reason": bot_registry.stop_reason(bot_id)}

        bot_registry.mark_stopped(bot_id, reason)
        await pub_socket.send_multipart([
            bot_id.encode('utf-8'),
            protocol.encode(protocol.BotCommand(
                bot_id=bot_id, action=protocol.BOT_STOP, reason=reason,
                sent_at=datetime.now())),
        ])

        cancelled: list[str] = []
        try:
            for report in await engine.cancel_open_orders(
                    hub.market_time, reason=f"{bot_id} stopped: {reason}",
                    only_bot=bot_id):
                await publish_report(pub_socket, report)
                cancelled.append(report.event.order_id)
        except Exception as e:
            # Said loudly and not raised: the bot is already stopping, and the
            # worst outcome here is a resting order nobody is watching, which
            # the operator needs to know about rather than see as a 500.
            log.error("%s%s stopped, but cancel of its resting orders failed; "
                      "still live at broker: %s", _at(hub.market_time), bot_id, e)

        asyncio.create_task(_reap_bot(bot_id))
        log.warning("%s%s stopped on req: %s (%d resting order(s) cancelled, "
                    "position kept)", _at(hub.market_time), bot_id, reason,
                    len(cancelled))
        return {"ok": True, "bot_id": bot_id, "reason": reason,
                "orders_cancelled": cancelled, "position_flattened": False}

    async def _reap_bot(bot_id: str, grace_s: float = 10.0) -> None:
        """Make sure a stopped bot's process actually goes away.

        A bot wedged inside its own strategy -- an infinite loop in on_bar, say
        -- never reads the socket and so never sees the command. Signalling it
        is the only thing left. Bounded by `grace_s` and then escalated,
        because a stop that silently does not stop is worse than a kill.
        """
        try:
            proc = procs[bots.index(bot_id)]
        except (ValueError, IndexError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace_s)
            return
        except asyncio.TimeoutError:
            pass
        log.warning("%s not exited %.0fs after stop, sending SIGTERM",
                    bot_id, grace_s)
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=grace_s)
        except asyncio.TimeoutError:
            log.error("%s ignored SIGTERM, killing it", bot_id)
            try:
                proc.kill()
            except Exception:
                pass
        except Exception:
            pass

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

        # -1 for a symbol with no bar yet: a bot that answered the startup
        # handshake reports seq -1 and is caught up.
        bot_registry.excuse_caught_up(
            {b: hub.seq_of(sym) for b, sym in bot_symbols.items()}, hub.bars)
        for bot_id in bot_registry.newly_silent(hub.bars, BOT_SILENT_BARS):
            log.error("%s%s silent for %d bars (exited, stalled or on another "
                      "engine); its orders are stale", _at(as_of), bot_id,
                      BOT_SILENT_BARS)
        if hub.bars % BOT_STATUS_EVERY == 0:
            for bot_id in bots:
                log_bots.info("%s%s", _at(as_of),
                              bot_registry.summary_line(bot_id))

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
            log.warning("%saccount read failed on bar %d (%d in a row): %s",
                        _at(as_of), hub.bars, account_read_failures, e)
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
                log_risk.error("%sKILL SWITCH: %s", _at(as_of), gate.halt_reason)
                for report in await engine.cancel_open_orders(as_of, "account unreadable"):
                    await publish_report(pub_socket, report)
            return
        if account_read_failures:
            log.info("%saccount readable again after %d bar(s)", _at(as_of),
                     account_read_failures)
            account_read_failures = 0

        equity = state.balance + sum(p.market_value for p in state.positions)
        # Record before the gate looks at it: a bar that trips the kill switch
        # is the most interesting point on the curve, so it has to be on it.
        recorder.observe(as_of, equity)
        tripped = gate.observe_equity(equity)
        if tripped:
            # A halt that leaves working orders out there is not a halt, so pull
            # them before refusing anything new.
            log_risk.error("%sKILL SWITCH: %s", _at(as_of), tripped)
            for report in await engine.cancel_open_orders(as_of, "risk halt"):
                await publish_report(pub_socket, report)

    # Replay only: after each bar, wait for every bot to answer it before the
    # clock moves. A bot sends its orders for a bar and then its BotStatus on
    # one PUSH socket, which keeps them in order, and handle_bot_messages
    # executes each intent before it reads the next message. So once a bot's
    # status for this bar is recorded, its orders for this bar have been
    # placed at this bar's market time. Without the wait they landed on a
    # later bar whenever the bot was slower than the stepping, which made
    # two --speed=0 runs disagree about orders and fills.
    unresponsive: set[str] = set()

    async def wait_for_bots(published: dict[str, int]) -> None:
        wanted = {b: published[sym] for b, sym in bot_symbols.items()
                  if sym in published and b not in unresponsive}
        answered = await bot_registry.wait_for(
            lambda: not bot_registry.behind(wanted), BAR_BARRIER_TIMEOUT_S)
        if answered:
            return
        late = bot_registry.behind(wanted)
        unresponsive.update(late)
        log.error("%s%s no answer to bar %d within %.0fs; no longer waited "
                  "for, replay not reproducible", _at(hub.market_time),
                  ",".join(late), hub.bars, BAR_BARRIER_TIMEOUT_S)

    # Only the live path consults the trading session. Under replay the bars
    # themselves came from real sessions, so there is nothing to gate and the
    # check would only cost a round trip per bar.
    hub = EventHub(account_client=account_client, clock=clock,
                   on_bar_end=report_resolved_orders,
                   session_check=(account_client.is_market_open
                                  if cfg.is_live else None),
                   after_publish=(wait_for_bots
                                  if isinstance(clock, ReplayClock) else None))
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
            bots=bots, stop_bot=stop_bot,
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
            log.error("%sshutdown cancel failed, orders may be live at "
                      "broker: %s", _at(hub.market_time), e)

        log.info("terminating all bots")
        for proc in procs:
            # Each in its own try: one bot that is already gone must not stop
            # the others being reaped, or they outlive master and go on
            # trading against a mirror nobody updates.
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass

        # What each bot last said. Worth printing even on a clean run: a bot
        # whose last word was 400 bars ago stopped reporting while master kept
        # going, and the fill count alone would not show that.
        for bot_id in bots:
            log_bots.info("%s", bot_registry.summary_line(bot_id))
        log.info("engine terminated")

        # After the bots are gone so the report is not interleaved with their
        # output, and before disconnect() because the fills are a server read.
        try:
            result = await asyncio.to_thread(recorder.build_result, account_client)
            if result is not None:
                print_run_report(result)
        except Exception as e:
            log_report.error("run report build failed: %s", e)

        # After the report, so a failure above still leaves the journal intact
        # on disk rather than half-flushed.
        recorder.close()
        account_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
