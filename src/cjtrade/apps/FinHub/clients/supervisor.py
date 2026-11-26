"""Starts and stops a run, so FinHub owns its lifetime.

WHY THE SUPERVISOR IS HERE AND NOT IN THE ENGINE
------------------------------------------------
A run needs two processes: the ArenaX broker-side server, and the engine (which
in turn spawns its bots). Neither can start the other — the engine connects to
a broker and gives up if it is not there, and the broker knows nothing about
engines. Something has to be above both, and it has to outlive a run in order
to start the next one. That is the UI's job, which is the same argument for the
web process being separate from the engine in the first place.

Tying the lifetime to FinHub's means a crashed or restarted FinHub does not
leave a broker holding a simulated account and an engine trading into it. Two
mechanisms, because one is not enough:

* each child is started in its own process **group**, so stopping a run kills
  the engine's bot subprocesses too and not just the engine;
* `shutdown()` runs from FastAPI's lifespan, so closing FinHub closes the run.

ONE RUN AT A TIME
-----------------
Not a simplification — a constraint of the engine as it stands. `protocol.py`
binds fixed ZMQ ports (5555 for the price feed, 5556 for order intents) and the
status API takes one port, so a second engine on this machine would either fail
to bind or, worse, have its bots subscribe to the first engine's bars. The
engine parameterises those ports but `cjtrade` passes the defaults, so until
it takes them as flags, two concurrent runs are not a thing to offer.
"""
import asyncio
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Optional

from cjtrade.pkgs.logger import get_logger

from .arenax_client import ArenaXClient

log = get_logger("FinHub.supervisor")

# How long to wait for the broker to report `running: true`. It logs in to the
# real broker and preloads a price range before it is usable, which on a cold
# cache is tens of seconds.
BROKER_READY_TIMEOUT_S = 90.0
# The engine answers /health as soon as its status site binds, which it does
# after the kbar fetch and clock alignment -- also slow on a cold cache.
ENGINE_READY_TIMEOUT_S = 180.0
POLL_INTERVAL_S = 0.5
# How long a child gets to exit on SIGTERM before SIGKILL.
GRACE_S = 10.0

VALID_MODES = ("backtest", "paper", "demo")

# What one bar can be: the engine replays 1m bars and has no interval flag, so
# anything else would be accepted here and silently ignored by the run.
BAR_INTERVALS = ("1m",)
# Taiwan tickers: 4 digits, sometimes with a letter suffix (e.g. 2330, 00632R).
# Validated rather than passed through because these end up in a child's argv
# and in URLs. No shell is involved anywhere here, so this is not about shell
# injection; it is about not asking the engine to watch something that cannot
# be a symbol and then debugging the result.
SYMBOL_RE = re.compile(r"^[0-9]{4,6}[A-Z]?$")


class SupervisorError(RuntimeError):
    """A run could not be started or stopped."""


@dataclass
class RunConfig:
    """A validated run request. Construct with `parse`, never directly from
    user input."""

    symbols: list
    mode: str = "backtest"
    broker: str = "arenax"
    days: int = 20
    fund: float = 1_000_000.0
    speed: float = 1.0
    start_date: str = ""          # "" -> let the server pick (possibly random)
    # What one bar IS, not how a chart is drawn. It decides what the strategy
    # is handed each step, so a window of 100 bars is 100 minutes at 1m and
    # 100 trading sessions at 1d.
    interval: str = "1m"
    arenax_port: int = 8802
    status_port: int = 8898

    @classmethod
    def parse(cls, raw: dict, *, default_arenax_port: int,
              default_status_port: int) -> "RunConfig":
        """Coerce and bound a request from the web. Raises SupervisorError.

        Bounds, not just types: `days` reaches the engine as a replay length,
        and asking for 20,000 days would have it fetch every bar it can find
        before anyone could stop it.
        """
        symbols = raw.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",")]
        symbols = [s.strip().upper() for s in symbols if s and s.strip()]
        if not symbols:
            raise SupervisorError("pick at least one symbol")
        if len(symbols) > 20:
            raise SupervisorError("at most 20 symbols per run")
        bad = [s for s in symbols if not SYMBOL_RE.match(s)]
        if bad:
            raise SupervisorError(f"not symbols: {', '.join(bad)}")

        mode = str(raw.get("mode") or "backtest").lower()
        if mode not in VALID_MODES:
            raise SupervisorError(f"mode must be one of {', '.join(VALID_MODES)}")

        # `x or default` would be wrong here: 0 is falsy, so days=0 and
        # speed=0 would silently become 20 and 1 and start a run nobody asked
        # for instead of being refused by the bounds below. Only a missing or
        # blank value takes the default.
        def _given(key, default):
            value = raw.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return default
            return value

        try:
            days = int(_given("days", 20))
            fund = float(_given("fund", 1_000_000))
            speed = float(_given("speed", 1))
        except (TypeError, ValueError) as exc:
            raise SupervisorError(f"days, fund and speed must be numbers: {exc}")
        if not 1 <= days <= 1825:
            raise SupervisorError("days must be between 1 and 1825 (5 years)")
        if not 1_000 <= fund <= 1_000_000_000:
            raise SupervisorError("fund must be between 1,000 and 1,000,000,000")
        # 0 is allowed and means "as fast as possible". The engine honours the
        # speed in backtest now, so this is the only way to ask for an unpaced
        # replay -- and it is what the UI defaults to, because that is how a
        # backtest behaved before the speed meant anything.
        if not 0 <= speed <= 100_000:
            raise SupervisorError("speed must be 0 (flat out) or a positive number")

        start_date = str(raw.get("start_date") or "").strip()
        if start_date:
            try:
                datetime.fromisoformat(start_date)
            except ValueError:
                raise SupervisorError(
                    f"start_date must be YYYY-MM-DD, got {start_date!r}")

        interval = str(raw.get("interval") or "1m").strip() or "1m"
        if interval not in BAR_INTERVALS:
            raise SupervisorError(
                f"interval must be one of {', '.join(BAR_INTERVALS)}, "
                f"got {interval!r}")

        return cls(symbols=symbols, mode=mode, days=days, fund=fund,
                   speed=speed, start_date=start_date, interval=interval,
                   arenax_port=default_arenax_port,
                   status_port=default_status_port)

    def as_dict(self) -> dict:
        return {
            "symbols": list(self.symbols), "mode": self.mode,
            "broker": self.broker, "days": self.days, "fund": self.fund,
            "speed": self.speed, "start_date": self.start_date,
            "interval": self.interval,
            "arenax_port": self.arenax_port, "status_port": self.status_port,
        }


@dataclass
class Child:
    """One managed process and where its output went."""
    name: str
    argv: list
    popen: subprocess.Popen
    log_path: Path
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def alive(self) -> bool:
        return self.popen.poll() is None

    @property
    def exit_code(self) -> Optional[int]:
        return self.popen.poll()

    def describe(self) -> dict:
        return {
            "name": self.name,
            "pid": self.popen.pid,
            "alive": self.alive,
            "exit_code": self.exit_code,
            "started_at": self.started_at.isoformat(),
            "log": str(self.log_path),
            "argv": list(self.argv),
        }


class RunSupervisor:
    """Owns at most one run's processes."""

    # Where a run's strategy files are written. A copy per run, not a pointer
    # at the database: somebody editing a strategy while it is trading must not
    # change what is already running.
    STRATEGY_DIR_NAME = "run_strategies"

    def __init__(self, log_dir: Path, python: str = sys.executable,
                 arenax_client_factory=None):
        # The broker and the engine run as modules of this interpreter's
        # cjtrade, so FinHub needs no checkout and no uv to start a run.
        self.python = python
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._children: list = []
        self._config: Optional[RunConfig] = None
        self._run_id: Optional[int] = None
        self._started_at: Optional[datetime] = None
        self._log_path: Optional[Path] = None
        # The engine's control-plane capability for the current run. Minted
        # here, handed to the engine in its environment at spawn, and never
        # written to a log or sent to a browser. None between runs, which is
        # also what stops a stale token being offered to a new engine.
        self._control_token: Optional[str] = None
        # bot_id -> the strategy id it is running, for this run. The engine
        # does not know about FinHub's database, so this is the only place the
        # two can be joined.
        self._bot_strategies: dict = {}
        # Injectable so the tests do not need a broker.
        self._client_factory = arenax_client_factory or (
            lambda base_url, api_key: ArenaXClient(base_url, api_key))
        # Serialises start/stop. Two POSTs arriving together must not each
        # decide the port is free and both spawn a server.
        self._lock = asyncio.Lock()

    # ── state ─────────────────────────────────────────────────────────────────

    def _child(self, name: str) -> Optional[Child]:
        # Last one wins: start() clears the list, so there is only ever one of
        # each name per run, but a dead child is kept until the next start or
        # stop so its exit code can still be read.
        found = [c for c in self._children if c.name == name]
        return found[-1] if found else None

    @property
    def engine_started(self) -> bool:
        """Has the engine been spawned at all, alive or not?

        Distinct from `engine_alive`, and the distinction matters: `start()`
        sets the run id, then waits up to 90s for the broker, and only then
        spawns the engine. For that whole window there is a run with no engine,
        which is not the same thing as a run whose engine has finished.
        """
        return self._child("engine") is not None

    @property
    def engine_alive(self) -> bool:
        child = self._child("engine")
        return bool(child and child.alive)

    @property
    def broker_alive(self) -> bool:
        return bool(self._child("broker") and self._child("broker").alive)

    @property
    def busy(self) -> bool:
        """Is a run in flight?

        The engine, specifically -- not "any child is alive". The broker
        outlives the engine during teardown, so counting it here made a
        finished run look like it was still going: the run row never got its
        summary written, and the next run was refused as a conflict.
        """
        return self.engine_alive

    @property
    def run_id(self) -> Optional[int]:
        return self._run_id

    @property
    def log_path(self) -> Optional[Path]:
        return self._log_path

    def describe(self) -> dict:
        return {
            "busy": self.busy,
            # Reported separately because they are different facts: the broker
            # can be up with no run in flight, which is the state right after
            # one finishes and right before the next starts.
            "engine_started": self.engine_started,
            "engine_alive": self.engine_alive,
            "broker_alive": self.broker_alive,
            "run_id": self._run_id,
            "config": self._config.as_dict() if self._config else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "children": [c.describe() for c in self._children],
            "python": self.python,
        }

    def engine_exit(self) -> Optional[int]:
        """The engine's exit code, or None while it runs or was never started.

        Readable after the process is gone, which is the whole point: a dead
        child is kept in the list until the next start or stop so the run
        watcher can still ask how it ended.
        """
        child = self._child("engine")
        return child.exit_code if child else None

    # ── starting ──────────────────────────────────────────────────────────────

    @property
    def control_token(self) -> Optional[str]:
        """The current run's control-plane capability, or None.

        Read by whoever needs to call the engine's one write route. Not
        exposed by `describe()` and never logged: a credential in a log file
        is a credential leaked.
        """
        return self._control_token

    @property
    def bot_strategies(self) -> dict:
        """bot_id -> strategy id, for the run in flight."""
        return dict(self._bot_strategies)

    def _write_strategies(self, run_id: int, strategies: list) -> list[dict]:
        """Write each strategy to its own file and build the engine's roster.

        `strategies` is a list of (strategy_id, name, symbol, source). The
        source is copied rather than referenced, because the database row can
        change while the run is going and the file the engine loaded should
        not.

        The filename is derived from the id, not the name: a name is free text
        and "../../etc/cron.d/x" is a name. The id is an integer from our own
        database.
        """
        run_dir = (self.log_dir.parent / self.STRATEGY_DIR_NAME
                   / f"run-{run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)

        roster = []
        self._bot_strategies = {}
        for index, (strategy_id, name, symbol, source) in enumerate(strategies,
                                                                    start=1):
            path = run_dir / f"strategy-{int(strategy_id)}.py"
            path.write_text(source, encoding="utf-8")
            bot_id = f"Bot_S{index}"
            roster.append({
                "bot_id": bot_id,
                "script": "bot_custom.py",
                "symbol": symbol,
                "extra": [str(path)],
            })
            self._bot_strategies[bot_id] = {
                "strategy_id": int(strategy_id), "name": name,
                "symbol": symbol,
            }
        return roster

    async def start(self, cfg: RunConfig, run_id: int,
                    strategies: Optional[list] = None) -> dict:
        """Bring up the broker (if needed) and then the engine.

        Order is not negotiable: the engine connects to the broker during
        startup and aborts if it is absent, so the broker has to be answering
        `running: true` first.

        `strategies` is a list of (id, name, symbol, source) to run as bots.
        Empty or None leaves the engine on its own built-in roster, which is
        what a run started before anybody wrote a strategy should do.
        """
        async with self._lock:
            if self.engine_alive:
                raise SupervisorError(
                    f"a run is already in flight (run {self._run_id}); "
                    f"stop it before starting another")
            # Forget the previous run's processes, dead or otherwise. A broker
            # still listening from last time is picked up below as a reuse.
            self._children = []

            self._config = cfg
            self._run_id = run_id
            self._started_at = datetime.now()
            stamp = self._started_at.strftime("%Y%m%d-%H%M%S")
            self._log_path = self.log_dir / f"run-{run_id}-{stamp}.log"
            # A fresh capability per run, so a token learned from one run is
            # useless against the next.
            self._control_token = secrets.token_urlsafe(32)
            self._bot_strategies = {}

            roster_path: Optional[Path] = None
            if strategies:
                roster = self._write_strategies(run_id, strategies)
                roster_path = (self.log_dir.parent / self.STRATEGY_DIR_NAME
                               / f"run-{run_id}" / "roster.json")
                roster_path.write_text(json.dumps(roster, indent=2),
                                       encoding="utf-8")
                log.info("run %d will spawn %d strategy bot(s): %s", run_id,
                         len(roster),
                         ", ".join(f"{r['bot_id']}={r['symbol']}"
                                   for r in roster))

            client = self._client_factory(
                f"http://127.0.0.1:{cfg.arenax_port}", "")
            broker_was_running = await client.is_up()

            try:
                if broker_was_running:
                    log.info("ArenaX already up on %s — reusing it",
                             cfg.arenax_port)
                else:
                    self._spawn_broker(cfg)
                    await self._await_broker(client)
                self._spawn_engine(cfg, roster_path)
            except Exception:
                # Never leave half a run behind: if the engine failed to spawn
                # we would otherwise keep a broker nobody is driving.
                await self._stop_children()
                raise

            return {
                "run_id": run_id,
                "broker_reused": broker_was_running,
                "log": str(self._log_path),
                "children": [c.describe() for c in self._children],
            }

    def _spawn_broker(self, cfg: RunConfig) -> None:
        argv = [self.python, "-m", "cjtrade.apps.ArenaX.brokerside_server",
                f"--backend={cfg.mode}", f"--port={cfg.arenax_port}"]
        env = dict(os.environ)
        # The server's own clock speed, which is a different thing from the
        # engine's: under ReplayClock the engine steps the server's clock bar
        # by bar, so this only matters to code that reads the server's clock
        # directly. Clamped away from 0 because the server multiplies by it
        # (start_date + elapsed * speed), where 0 means a frozen clock -- and
        # 0 here means the opposite, "do not pace the engine".
        env["AX_BACKTEST_PLAYBACK_SPEED"] = str(cfg.speed if cfg.speed > 0 else 1.0)
        # How many days of prices the server loads. It has to be told: nothing
        # passed --days along, so it used its .cjsys value (300) whatever the
        # form asked for, and the overrun was silent -- the snapshot route
        # cannot report having run out, so it repeated its last price for every
        # bar past the end and the run reported on a flat feed.
        #
        # days + 1, and the +1 is load-bearing: the server snaps start_date to
        # 09:00 and loads [start_date, start_date + N], so at N == --days the
        # final day's session after 09:00 falls outside. Run 18 asked for 300
        # against a 300-day server and still froze for all 233 bars of its
        # last day.
        #
        # Via the environment because arenaxd has no such flag; load_cjsys
        # loads its file with override=False, then reads os.environ, so this
        # wins.
        env["AX_BACKTEST_DURATION_DAYS"] = str(cfg.days + 1)
        self._children.append(self._spawn("broker", argv, env))

    def _spawn_engine(self, cfg: RunConfig,
                      roster_path: Optional[Path] = None) -> None:
        # Every field the form would ask for is passed as a flag, because the
        # engine's load_config() only skips prompting for fields whose flag is
        # present in argv. Miss one and the process blocks on stdin forever,
        # which from here looks exactly like a hang.
        argv = [
            self.python, "-m", "cjtrade.apps.CJTrade.main",
            f"--broker={cfg.broker}",
            f"--mode={cfg.mode}",
            f"--watch-list={','.join(cfg.symbols)}",
            f"--speed={cfg.speed:g}",
            f"--days={cfg.days}",
            f"--fund={cfg.fund:g}",
            # Intentionally allowed to be empty: the engine reads "" as "take
            # the server's own timeline origin" rather than inventing a date.
            f"--start-date={cfg.start_date}",
        ]
        if roster_path is not None:
            argv.append(f"--roster={roster_path}")
        env = dict(os.environ)
        env["CJ_ENGINE_STATUS_PORT"] = str(cfg.status_port)
        env["ARENAX_PORT"] = str(cfg.arenax_port)
        # The control plane's capability. In the environment rather than argv
        # because argv is visible to every process on the box through ps, and
        # a token in ps is a token anyone can read. Without this the engine's
        # write routes refuse outright -- see status_api's _authenticated.
        env["CJ_ENGINE_CONTROL_TOKEN"] = self._control_token or ""
        # Unbuffered, so the log file is useful while the run is still going
        # instead of arriving in 8KB lumps.
        env["PYTHONUNBUFFERED"] = "1"
        self._children.append(self._spawn("engine", argv, env))

    def _spawn(self, name: str, argv: list, env: dict) -> Child:
        log.info("[%s] %s", name, " ".join(argv))
        handle = open(self._log_path, "a", buffering=1)
        handle.write(f"\n===== {name} started {datetime.now().isoformat()} =====\n")
        handle.write(f"$ {' '.join(argv)}\n")
        handle.flush()
        try:
            popen = subprocess.Popen(
                argv,
                cwd=str(self.log_dir),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # Its own process group, so stopping the engine also stops the
                # bot subprocesses it spawned. Without this, terminating the
                # engine orphans its bots, and a bot that outlives its master
                # keeps a stale ledger mirror and goes on acting on it.
                start_new_session=True,
            )
        except OSError as exc:
            handle.close()
            raise SupervisorError(f"could not start the {name} ({argv[0]}): {exc}") from exc
        return Child(name=name, argv=argv, popen=popen, log_path=self._log_path)

    async def _await_broker(self, client) -> None:
        deadline = time.monotonic() + BROKER_READY_TIMEOUT_S
        while time.monotonic() < deadline:
            broker = next((c for c in self._children if c.name == "broker"), None)
            if broker is not None and not broker.alive:
                raise SupervisorError(
                    f"the ArenaX server exited with code {broker.exit_code} "
                    f"before becoming ready — see {self._log_path}")
            try:
                health = await client.health()
            except Exception:
                health = None
            if health and health.get("running") is True:
                log.info("ArenaX ready (data_readiness=%s)",
                         health.get("data_readiness"))
                return
            await asyncio.sleep(POLL_INTERVAL_S)
        raise SupervisorError(
            f"the ArenaX server did not report running within "
            f"{BROKER_READY_TIMEOUT_S:.0f}s — see {self._log_path}")

    # ── stopping ──────────────────────────────────────────────────────────────

    async def stop(self) -> dict:
        """Stop the engine first, then the broker.

        That order matters: killing the broker out from under a running engine
        makes every account read fail, and the engine's teardown wants the
        broker alive to cancel resting orders and read the fill history for its
        report.
        """
        async with self._lock:
            result = await self._stop_children()
            return result

    async def _stop_children(self) -> dict:
        stopped = []
        for name in ("engine", "broker"):
            for child in [c for c in self._children if c.name == name]:
                stopped.append(await self._stop_child(child))
        self._children = []
        # The capability dies with the run it was minted for, so a token
        # learned from this run cannot be offered to the next engine. Cleared
        # after the children are gone rather than before, because stopping
        # them is the last thing it is needed for.
        self._control_token = None
        self._bot_strategies = {}
        return {"stopped": stopped}

    async def _stop_child(self, child: Child) -> dict:
        if not child.alive:
            return {"name": child.name, "pid": child.popen.pid,
                    "was_alive": False, "exit_code": child.exit_code}

        pid = child.popen.pid
        # The whole group: the engine's bots are its children, and SIGTERM to
        # the engine alone would leave them running. The engine converts
        # SIGTERM into a KeyboardInterrupt so its own teardown still happens.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(pid), sig)
            except ProcessLookupError:
                break
            except PermissionError as exc:
                log.warning("could not signal %s group: %s", child.name, exc)
                break
            deadline = time.monotonic() + (GRACE_S if sig == signal.SIGTERM else 2.0)
            while time.monotonic() < deadline:
                if not child.alive:
                    break
                await asyncio.sleep(0.2)
            if not child.alive:
                break
        log.info("stopped %s (pid %s, exit %s)", child.name, pid, child.exit_code)
        return {"name": child.name, "pid": pid, "was_alive": True,
                "exit_code": child.exit_code}

    async def shutdown(self) -> None:
        """Called from FastAPI's lifespan. This is the lifetime tie."""
        if self.busy:
            log.info("FinHub is shutting down — stopping the run it started")
            await self._stop_children()

    # ── logs ──────────────────────────────────────────────────────────────────

    def tail(self, lines: int = 200, path: Optional[Path] = None) -> str:
        """Last `lines` of a run's captured output.

        Reads the whole file rather than seeking: a run's log is megabytes at
        most, and seeking backwards through a file being appended to by two
        processes is a good way to return half a line.
        """
        target = Path(path) if path else self._log_path
        if not target or not target.is_file():
            return ""
        with open(target, errors="replace") as handle:
            return "".join(handle.readlines()[-max(1, lines):])
