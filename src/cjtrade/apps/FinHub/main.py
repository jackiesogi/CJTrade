"""FinHub — the front end for the CJTrade trading engine.

Three things the UI needs and three sources for them, each the only one that
can answer its own questions:

    engine  (:8898, read-only)  what the bots are doing right now
    broker  (:8802)             the account, the orders, the market
    FinHub's own DB             that a run happened, and who placed what by hand

Every one of those calls is made here, server-side. The browser talks only to
FinHub — see clients/__init__.py for why that is the whole design and not a
detail.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from cjtrade.apps.FinHub import auth
from cjtrade.apps.FinHub import models
from cjtrade.apps.FinHub import schemas
from cjtrade.apps.FinHub.auth import get_current_user
from cjtrade.apps.FinHub.clients import ArenaXClient
from cjtrade.apps.FinHub.clients import BadSegment
from cjtrade.apps.FinHub.clients import BrokerError
from cjtrade.apps.FinHub.clients import EngineClient
from cjtrade.apps.FinHub.clients import EngineUnavailable
from cjtrade.apps.FinHub.clients import RunConfig
from cjtrade.apps.FinHub.clients import RunSupervisor
from cjtrade.apps.FinHub.clients import StrategyTool
from cjtrade.apps.FinHub.clients import StrategyToolError
from cjtrade.apps.FinHub.clients import SupervisorError
from cjtrade.apps.FinHub.config import settings
from cjtrade.apps.FinHub.database import engine as db_engine
from cjtrade.apps.FinHub.database import get_db
from cjtrade.pkgs.logger import get_logger
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import HTMLResponse
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

log = get_logger("FinHub")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

engine_client = EngineClient(settings.engine_base_url)
broker_client = ArenaXClient(settings.arenax_base_url, settings.ARENAX_API_KEY)
supervisor = RunSupervisor(python=settings.PYTHON,
                           log_dir=settings.RUN_LOG_DIR)
strategy_tool = StrategyTool(python=settings.PYTHON)
# How the engine client finds the current run's control token. Asked for each
# call rather than copied, so it is never stale: the token belongs to a run,
# and the supervisor forgets it the moment that run's children are gone.
engine_client.token_provider = lambda: supervisor.control_token


# ══════════════════════════════════════════════════════════════════════════════
#  Lifespan
# ══════════════════════════════════════════════════════════════════════════════

def _close_out_orphaned_runs() -> None:
    """Mark runs that were in flight when FinHub last stopped.

    The supervisor keeps its children in memory, so a FinHub that is killed --
    a reboot, a crash, a Ctrl-C in the wrong window -- comes back with no idea
    that run 10 ever existed. `_watch_run` then skips it forever, because it
    bails on `run_id is None`, and the row sits at "running" describing
    processes that died with the machine.

    Said as "interrupted" rather than "finished" or "failed": nothing is known
    about how it ended, and claiming either would be inventing a result.
    """
    from cjtrade.apps.FinHub.database import SessionLocal

    with SessionLocal() as db:
        stale = (db.query(models.Run)
                 .filter(models.Run.status.in_(("starting", "running")))
                 .all())
        for run in stale:
            run.status = "interrupted"
            run.ended_at = run.ended_at or datetime.utcnow()
            run.error = (run.error or
                         "FinHub stopped while this run was in flight, so how "
                         "it ended was never recorded. Its processes did not "
                         "survive.")
        if stale:
            db.commit()
            log.warning("marked %d run(s) as interrupted: %s", len(stale),
                        ", ".join(str(r.id) for r in stale))


def _ensure_schema() -> None:
    """Add columns that `create_all` cannot, because the table already exists.

    There is no migration tool here, and for a handful of nullable columns on
    a single-file SQLite database one is hard to justify. What is not
    justifiable is a new column silently not existing: `create_all` creates
    missing *tables* and ignores missing columns, so an older finhub.db would
    answer every query with "no such column" until somebody deleted it.

    Narrow on purpose -- only ever adds a nullable column. Anything that needs
    a backfill, a rename or a type change needs a real migration and should
    not be smuggled in here.
    """
    from sqlalchemy import inspect
    from sqlalchemy import text

    additions = {
        # (table, column): DDL
        ("bot_slots", "strategy_id"): "INTEGER REFERENCES strategies(id)",
        # NOT NULL with a default, so existing rows become enabled rather than
        # null -- a strategy that predates the column was trading, and the
        # migration should not quietly switch it off.
        ("strategies", "enabled"): "INTEGER NOT NULL DEFAULT 1",
        ("strategies", "seeded_from"): "VARCHAR",
        ("users", "examples_seeded"): "INTEGER NOT NULL DEFAULT 0",
        # Defaulted to 1m because that is what every run before this column
        # existed actually used -- the engine had the interval hardcoded.
        ("runs", "interval"): "VARCHAR NOT NULL DEFAULT '1m'",
    }

    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    with db_engine.begin() as connection:
        for (table, column), ddl in additions.items():
            if table not in tables:
                continue            # create_all will make it with the column
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.warning("added %s.%s to an existing database", table, column)


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=db_engine)
    _ensure_schema()
    # Before the watcher starts, so it never sees a row it cannot explain.
    _close_out_orphaned_runs()
    log.info("engine status API : %s", settings.engine_base_url)
    log.info("arenax broker     : %s", settings.arenax_base_url)
    log.info("run logs          : %s", settings.RUN_LOG_DIR)
    watcher = asyncio.create_task(_watch_run(), name="run_watcher")
    try:
        yield
    finally:
        watcher.cancel()
        # This is the lifetime tie the supervisor exists for: closing FinHub
        # closes the run it started, rather than leaving an engine trading into
        # a broker with nobody watching either.
        await supervisor.shutdown()


async def _watch_run() -> None:
    """Notice when the engine process ends and close out its Run row.

    Polling rather than waiting on the process: the row has to be updated from
    the engine's *last reported* state, and that has to be read before the
    status API goes away with the process. So this samples while it is alive
    and writes what it last saw once it is not.
    """
    from cjtrade.apps.FinHub.database import SessionLocal

    # The engine's own numbers, kept from the last successful poll. They have
    # to be remembered rather than fetched at the end, because the thing that
    # reports them is the process that just exited.
    last_status: dict = {}
    last_trips: dict = {}

    while True:
        try:
            await asyncio.sleep(2.0)
            run_id = supervisor.run_id
            # Nothing to watch, or the engine has not been spawned yet. The
            # second case is the whole reason this is not just `not busy`:
            # starting a run sets the run id and then waits for the broker, so
            # for up to a minute and a half there is a run with no engine, and
            # treating that as "the engine has exited" finalised runs before
            # they began.
            if run_id is None or not supervisor.engine_started:
                continue

            if supervisor.engine_alive:
                try:
                    status = await engine_client.status()
                except EngineUnavailable:
                    status = None       # status site already torn down
                if status:
                    last_status = status
                    with SessionLocal() as db:
                        run = db.get(models.Run, run_id)
                        if run is not None and run.status == "starting":
                            run.status = "running"
                            run.session_id = status.get("session_id")
                            db.commit()
                    try:
                        trips = await engine_client.roundtrips()
                        if trips and trips.get("available"):
                            last_trips = trips
                    except EngineUnavailable:
                        pass
                continue

            # The engine is gone. Write what it last said, then release the
            # broker it was driving.
            exit_code = supervisor.engine_exit()
            with SessionLocal() as db:
                run = db.get(models.Run, run_id)
                if run is not None and run.ended_at is None:
                    _finalise_run(run, last_status, last_trips, exit_code,
                                  supervisor.tail(400))
                    db.commit()
                    log.info("run %s %s (exit %s)", run_id, run.status, exit_code)
            last_status, last_trips = {}, {}
            # Stops the leftover broker. Deliberate: a server reused across two
            # runs hands the second one the first one's balance, because
            # AX_STATE_FILE is commented out in every .cjsys and fresh state is
            # per server process. Ending it here is what makes the next run
            # start from a clean account.
            await supervisor.stop()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("run watcher hiccup — continuing")


def _finalise_run(run: models.Run, status: dict, trips: dict,
                  exit_code: Optional[int], tail: str) -> None:
    """Copy the engine's last word onto the Run row.

    Done from remembered samples rather than a fresh read, because by now there
    is no engine to ask. A run whose engine never reported anything keeps
    nulls, which is the honest answer and is why the UI offers the log for
    those instead of a summary.
    """
    run.ended_at = datetime.utcnow()
    run.exit_code = exit_code

    # A run someone stopped on purpose keeps that status: "stopped" and
    # "failed" are different facts and the UI shows them differently.
    if run.status == "stopped":
        pass
    elif exit_code not in (0, None):
        run.status = "failed"
        # The last few lines are where the traceback is; the whole tail would
        # not fit in a column worth reading.
        run.error = "\n".join(tail.strip().splitlines()[-12:]) or None
    else:
        run.status = "finished"

    progress = status.get("progress") or {}
    equity = status.get("equity") or {}
    risk = status.get("risk") or {}
    run.bars_served = progress.get("bars_served")
    run.final_equity = equity.get("current")
    run.pnl = equity.get("pnl")
    run.halt_reason = risk.get("halt_reason")
    if run.session_id is None:
        run.session_id = status.get("session_id")

    run.fills = trips.get("fills")
    run.round_trips = trips.get("closed")
    run.win_rate = trips.get("win_rate_pct")


def _audit(db: Session, user: models.User, action: str, target: str = "",
           details: str = "") -> None:
    db.add(models.AuditLog(user_id=user.id, action=action, target=str(target),
                           details=details))


app = FastAPI(
    title="FinHub",
    description="Front end for the CJTrade trading engine: run control, "
                "bot monitoring, manual trading.",
    version="0.2.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")),
          name="static")


# ══════════════════════════════════════════════════════════════════════════════
#  Pages
# ══════════════════════════════════════════════════════════════════════════════

PAGES = ("dashboard", "runs", "bots", "positions", "orders", "market",
         "trade", "editor", "audit")


@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.get("/register", response_class=HTMLResponse, tags=["Frontend"])
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")


# ══════════════════════════════════════════════════════════════════════════════
#  Identity
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/auth/register", response_model=schemas.UserSchema,
          tags=["Auth"])
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(
        or_(models.User.username == user_in.username,
            models.User.email == user_in.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Identity already exists.")
    user = models.User(username=user_in.username, email=user_in.email,
                       hashed_password=auth.hash_password(user_in.password))
    db.add(user)
    db.flush()
    # The three strategies the engine's built-in bots run, as editable copies.
    # Seeded here rather than on first page load so a new account has something
    # to read on day one -- a blank editor is the worst place to learn an API
    # from. Best effort: a checkout that cannot produce templates must not stop
    # somebody registering.
    _seed_examples_for(db, user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/v1/auth/login", tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password,
                                            user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return {"access_token": auth.create_access_token(data={"sub": user.username}),
            "token_type": "bearer"}


@app.get("/api/v1/auth/me", response_model=schemas.UserSchema, tags=["Auth"])
def whoami(current_user: models.User = Depends(get_current_user)):
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
#  Engine  — the live view of a run
#
#  Every route answers 200 with {"available": false} when there is no engine,
#  because "no run in flight" is the normal state of this system and a 502
#  would have the UI render an error for it.
# ══════════════════════════════════════════════════════════════════════════════

def _absent(reason: str = "no run in flight") -> dict:
    return {"available": False, "reason": reason}


# What a page is told when an upstream fails. Fixed text: the exception's own
# message names URLs, ports and upstream errors, which belong in FinHub's log,
# not in a response.
ENGINE_DOWN = "the engine is not reachable; see FinHub's log for why"
BROKER_DOWN = "the broker is not reachable; see FinHub's log for why"
TOOL_DOWN = "strategy-tool is not available; see FinHub's log for why"


def _engine_absent(exc: Exception) -> dict:
    log.warning("engine status API: %s", exc)
    return _absent(ENGINE_DOWN)


@app.exception_handler(BadSegment)
async def _bad_segment(request: Request, exc: BadSegment):
    """A symbol, order id or bot id that cannot be used in an upstream URL."""
    from fastapi.responses import JSONResponse
    log.warning("rejected %s: %s", request.url.path, exc)
    return JSONResponse(status_code=422,
                        content={"detail": "invalid symbol, order id or bot id"})


@app.get("/api/v1/engine/status", tags=["Engine"])
async def engine_status(current_user: models.User = Depends(get_current_user)):
    try:
        status = await engine_client.status()
    except EngineUnavailable as exc:
        return _engine_absent(exc)
    return {"available": True, "status": status,
            "supervisor": supervisor.describe()}


@app.get("/api/v1/engine/bots", tags=["Engine"])
async def engine_bots(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, "bots": await engine_client.bots()}
    except EngineUnavailable as exc:
        return _engine_absent(exc)


@app.get("/api/v1/bots", tags=["Engine"])
async def bots_overview(db: Session = Depends(get_db),
                        current_user: models.User = Depends(get_current_user)):
    """Every bot you have, running or not.

    `/api/v1/engine/bots` is the engine's live view and nothing else: between
    runs it is empty, so a strategy somebody wrote was invisible until a run
    happened to be in flight. This answers the question the page is actually
    asking -- what bots exist, and which of them are alive right now -- by
    putting the saved strategies and the engine's live report side by side.

    A live bot that matches none of your strategies is still listed. The engine
    ships built-in bots, and a bot that is trading must never be missing from
    the page that shows bots.
    """
    live: dict = {}
    engine_available = True
    engine_reason = ""
    try:
        live = await engine_client.bots() or {}
    except EngineUnavailable as exc:
        engine_available = False
        log.warning("engine status API: %s", exc)
        engine_reason = ENGINE_DOWN

    # bot_id -> the most recent slot that used it, across this user's runs.
    # Most recent, because a bot id is reused from run to run and the live
    # report is about the newest one.
    slots: dict[str, models.BotSlot] = {}
    for slot in (db.query(models.BotSlot)
                 .join(models.Run, models.BotSlot.run_id == models.Run.id)
                 .filter(models.Run.owner_id == current_user.id)
                 .order_by(models.Run.id.desc()).all()):
        slots.setdefault(slot.bot_id, slot)

    bot_for_strategy = {s.strategy_id: bot_id for bot_id, s in slots.items()
                        if s.strategy_id is not None}

    out: list[dict] = []
    claimed: set[str] = set()

    for strategy in (db.query(models.Strategy)
                     .filter(models.Strategy.owner_id == current_user.id)
                     .order_by(models.Strategy.updated_at.desc(),
                               models.Strategy.id.desc()).all()):
        bot_id = bot_for_strategy.get(strategy.id)
        status = live.get(bot_id) if bot_id else None
        if bot_id is not None and bot_id in live:
            claimed.add(bot_id)
        out.append({
            "kind": "strategy",
            "strategy_id": strategy.id,
            "bot_id": bot_id,
            "name": strategy.name,
            "symbol": strategy.symbol,
            "live": status is not None,
            "enabled": bool(strategy.enabled),
            "seeded_from": strategy.seeded_from,
            "check_ok": strategy.last_check_ok,
            "check_error": strategy.last_check_error,
            "updated_at": strategy.updated_at,
            "status": status,
        })

    for bot_id, status in live.items():
        if bot_id in claimed:
            continue
        slot = slots.get(bot_id)
        out.append({
            "kind": "engine",
            "strategy_id": None,
            "bot_id": bot_id,
            # The name recorded when the run started, which survives the
            # strategy being renamed or deleted.
            "name": (slot.strategy if slot and slot.strategy else bot_id),
            "symbol": (slot.symbol if slot else ""),
            "live": True,
            # Not a strategy of ours, so there is no flag to report and
            # nothing here can switch it off.
            "enabled": None,
            "seeded_from": None,
            "check_ok": None,
            "check_error": None,
            "updated_at": None,
            "status": status,
        })

    return {"engine_available": engine_available, "reason": engine_reason,
            "bots": out}


@app.get("/api/v1/engine/bots/{bot_id}/history", tags=["Engine"])
async def engine_bot_history(bot_id: str, limit: int = 120,
                             current_user: models.User = Depends(get_current_user)):
    try:
        history = await engine_client.bot_history(bot_id, limit=limit)
    except EngineUnavailable as exc:
        return _engine_absent(exc)
    if history is None:
        raise HTTPException(status_code=404, detail=f"no such bot: {bot_id}")
    return {"available": True, **history}


@app.get("/api/v1/engine/equity", tags=["Engine"])
async def engine_equity(limit: int = 1000,
                        current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await engine_client.equity(limit=limit))}
    except EngineUnavailable as exc:
        return _engine_absent(exc)


@app.get("/api/v1/engine/roundtrips", tags=["Engine"])
async def engine_roundtrips(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await engine_client.roundtrips())}
    except EngineUnavailable as exc:
        return _engine_absent(exc)


# ══════════════════════════════════════════════════════════════════════════════
#  Broker  — one route per shell command, see README for the mapping
# ══════════════════════════════════════════════════════════════════════════════

def _broker_call(coro):
    """Turn a BrokerError into a 502 with the broker's own words.

    502 and not 500: the fault is upstream, and saying so is the difference
    between "FinHub is broken" and "start the ArenaX server".
    """
    async def run():
        try:
            return await coro
        except BrokerError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return run()


@app.get("/api/v1/broker/health", tags=["Broker"])
async def broker_health(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await broker_client.health())}
    except BrokerError as exc:
        log.warning("broker: %s", exc)
        return _absent(BROKER_DOWN)


@app.get("/api/v1/broker/account", tags=["Broker"])
async def broker_account(current_user: models.User = Depends(get_current_user)):
    """balance + lspos + lsodr in one read."""
    return await _broker_call(broker_client.account())


@app.get("/api/v1/broker/orders", tags=["Broker"])
async def broker_orders(current_user: models.User = Depends(get_current_user)):
    """lsodr."""
    return {"orders": await _broker_call(broker_client.orders())}


@app.get("/api/v1/broker/fills", tags=["Broker"])
async def broker_fills(session_id: Optional[str] = None,
                       current_user: models.User = Depends(get_current_user)):
    """Fill history with the commission and tax the broker charged."""
    return await _broker_call(broker_client.fills(session_id=session_id))


@app.get("/api/v1/broker/snapshot", tags=["Broker"])
async def broker_snapshot(symbols: str,
                          current_user: models.User = Depends(get_current_user)):
    """ohlcv. `symbols` is comma separated, as the shell takes them."""
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not wanted:
        raise HTTPException(status_code=422, detail="no symbols given")
    if len(wanted) > 20:
        raise HTTPException(status_code=422, detail="at most 20 symbols")
    return {"snapshots": await _broker_call(broker_client.snapshots(wanted))}


@app.get("/api/v1/broker/kbars", tags=["Broker"])
async def broker_kbars(symbol: str, start: str, end: str, interval: str = "1m",
                       current_user: models.User = Depends(get_current_user)):
    """kbars / replay. Range is [start, end) — end is exclusive."""
    return {"symbol": symbol,
            "kbars": await _broker_call(
                broker_client.kbars(symbol.strip().upper(), start, end, interval))}


@app.get("/api/v1/broker/clock", tags=["Broker"])
async def broker_clock(current_user: models.User = Depends(get_current_user)):
    """date / info. Naive Asia/Taipei — do not convert it in the UI."""
    clock = await _broker_call(broker_client.clock())
    return {"clock": clock,
            "market_open": await _broker_call(broker_client.is_market_open())}


@app.post("/api/v1/broker/orders", response_model=schemas.ManualOrderSchema,
          tags=["Broker"])
async def place_manual_order(order_in: schemas.OrderCreate,
                             db: Session = Depends(get_db),
                             current_user: models.User = Depends(get_current_user)):
    """buy / sell, by hand.

    Read this before using it: a manual order goes straight to the broker, so
    the engine's RiskGate never sees it. The per-bot allocation, the orders-
    per-bar limit, the duplicate check and the kill switch do not apply. The
    broker still checks what a broker checks — price, quantity, trading limit,
    balance, inventory — and refuses with a reason, which comes back as a
    REJECTED status rather than an error.

    It is also invisible to the bots: their ledger mirrors are built from the
    engine's order reports, so a manual fill moves the real balance underneath
    a bot that does not know it happened. Hence the audit row and the `confirm`
    flag.
    """
    if not order_in.confirm:
        raise HTTPException(
            status_code=422,
            detail="A manual order bypasses the engine's risk gate. "
                   "Set confirm=true to acknowledge.")

    result = await _broker_call(broker_client.place_order(
        symbol=order_in.symbol.strip().upper(),
        action=order_in.action,
        quantity=order_in.quantity,
        price=order_in.price,
        odd_lot=order_in.odd_lot,
        # Tagged, so this order is identifiable in the broker's fill history
        # as not having come from a bot. The engine filters its own report by
        # session_id, so an untagged manual fill would be silently excluded
        # from the run report while still having moved the balance.
        opt_field={"source": "finhub-manual", "user": current_user.username},
    ))

    record = models.ManualOrder(
        owner_id=current_user.id,
        run_id=supervisor.run_id,
        order_id=result["order_id"],
        symbol=order_in.symbol.strip().upper(),
        action=order_in.action,
        quantity=order_in.quantity,
        price=order_in.price,
        order_lot="IntraDayOdd" if order_in.odd_lot else "Common",
        status=result["status"],
        message=result["message"],
    )
    db.add(record)
    _audit(db, current_user, "MANUAL_ORDER", result["order_id"],
           f"{order_in.action} {order_in.symbol} x{order_in.quantity} "
           f"@ {order_in.price} -> {result['status']}")
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/v1/broker/manual-orders",
         response_model=list[schemas.ManualOrderSchema], tags=["Broker"])
def list_manual_orders(limit: int = 50, db: Session = Depends(get_db),
                       current_user: models.User = Depends(get_current_user)):
    """Which orders a human placed. The broker cannot answer this."""
    return (db.query(models.ManualOrder)
            .filter(models.ManualOrder.owner_id == current_user.id)
            .order_by(models.ManualOrder.id.desc())
            .limit(max(1, min(limit, 500))).all())


@app.delete("/api/v1/broker/orders/{order_id}", tags=["Broker"])
async def cancel_order(order_id: str, db: Session = Depends(get_db),
                       current_user: models.User = Depends(get_current_user)):
    result = await _broker_call(broker_client.cancel_order(order_id))
    _audit(db, current_user, "CANCEL_ORDER", order_id, result["status"])
    db.commit()
    return result


@app.post("/api/v1/broker/orders/cancel-all", tags=["Broker"])
async def cancel_all_orders(db: Session = Depends(get_db),
                            current_user: models.User = Depends(get_current_user)):
    """The shell's `cancel`: every order the broker will still cancel.

    Including a bot's. A run in flight will find its resting order gone and
    report it as cancelled to the bot, which is handled — but it is the bot's
    plan you just changed, so the UI asks first.
    """
    results = await _broker_call(broker_client.cancel_all())
    cancelled = [r for r in results if not r.get("skipped")
                 and r.get("status") == "CANCELLED"]
    _audit(db, current_user, "CANCEL_ALL", "",
           f"{len(cancelled)} cancelled of {len(results)} order(s)")
    db.commit()
    return {"results": results, "cancelled": len(cancelled),
            "examined": len(results)}


# ══════════════════════════════════════════════════════════════════════════════
#  Runs
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/runs", response_model=list[schemas.RunSchema], tags=["Runs"])
def list_runs(limit: int = 50, db: Session = Depends(get_db),
              current_user: models.User = Depends(get_current_user)):
    return (db.query(models.Run)
            .filter(models.Run.owner_id == current_user.id)
            .order_by(models.Run.id.desc())
            .limit(max(1, min(limit, 200))).all())


@app.get("/api/v1/runs/{run_id}", response_model=schemas.RunSchema, tags=["Runs"])
def get_run(run_id: int, db: Session = Depends(get_db),
            current_user: models.User = Depends(get_current_user)):
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/api/v1/runs", response_model=schemas.RunSchema, status_code=201,
          tags=["Runs"])
async def start_run(run_in: schemas.RunCreate, db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    """Start a backtest: bring up the broker, then the engine.

    Authenticated, because this spawns processes on the host. It runs a fixed
    program with validated arguments and no shell, so the request cannot choose
    what to execute — only how the engine is configured. `RunConfig.parse`
    bounds every number, because `days` becomes a replay length and an absurd
    one would have the engine fetching bars for minutes before anything could
    interrupt it.
    """
    try:
        cfg = RunConfig.parse(run_in.model_dump(),
                              default_arenax_port=settings.ARENAX_PORT,
                              default_status_port=settings.ENGINE_STATUS_PORT)
    except SupervisorError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run = models.Run(
        owner_id=current_user.id, broker=cfg.broker, mode=cfg.mode,
        symbols=",".join(cfg.symbols), days=cfg.days, fund=cfg.fund,
        speed=cfg.speed, start_date=cfg.start_date, interval=cfg.interval,
        arenax_port=cfg.arenax_port, status_port=cfg.status_port,
        status="starting",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Which strategies this run will trade: yours, switched on, known to
    # compile, and for a symbol this run is watching.
    #
    # The symbol filter is not a nicety. The engine refuses to start a bot
    # whose symbol nobody publishes -- it would sit on a topic that never
    # carries a bar and then exit on its silence timer, which in the log looks
    # like a crash. Better to leave it out here and say so.
    #
    # `last_check_ok == 1` rather than "not known to be broken": a strategy
    # that has never been checked would be found broken by the engine at
    # startup, and finding out then costs a whole run.
    watched = set(cfg.symbols)
    candidates = (db.query(models.Strategy)
                  .filter(models.Strategy.owner_id == current_user.id,
                          models.Strategy.enabled == 1)
                  .order_by(models.Strategy.id).all())
    chosen = [s for s in candidates
              if s.symbol in watched and s.last_check_ok == 1]
    skipped = [f"{s.name} ({s.symbol}: "
               + ("not in the watch list" if s.symbol not in watched
                  else "not checked yet" if s.last_check_ok is None
                  else "has errors") + ")"
               for s in candidates if s not in chosen]

    try:
        info = await supervisor.start(
            cfg, run.id,
            strategies=[(s.id, s.name, s.symbol, s.source) for s in chosen])
    except SupervisorError as exc:
        run.status = "failed"
        run.error = str(exc)
        run.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        raise HTTPException(status_code=409, detail=str(exc))

    run.log_path = info["log"]
    # One slot per bot the engine was actually asked to spawn, carrying the
    # strategy id so the bots page can label a live bot with the strategy it is
    # running. When no strategy qualified, the engine falls back to its own
    # built-in roster and there is nothing of ours to record.
    for bot_id, meta in supervisor.bot_strategies.items():
        db.add(models.BotSlot(run_id=run.id, bot_id=bot_id,
                              strategy=meta["name"], symbol=meta["symbol"],
                              strategy_id=meta["strategy_id"]))
    if skipped:
        log.info("run %d left out %d strategy(ies): %s", run.id, len(skipped),
                 "; ".join(skipped))
    _audit(db, current_user, "START_RUN", str(run.id),
           f"{cfg.mode} {','.join(cfg.symbols)} interval={cfg.interval} "
           f"days={cfg.days} "
           f"fund={cfg.fund:g} start={cfg.start_date or 'server default'} "
           f"bots={len(supervisor.bot_strategies) or 'engine default'}"
           + (f" skipped={len(skipped)}" if skipped else ""))
    db.commit()
    db.refresh(run)
    return run


@app.delete("/api/v1/runs/{run_id}", tags=["Runs"])
async def stop_run(run_id: int, db: Session = Depends(get_db),
                   current_user: models.User = Depends(get_current_user)):
    """Stop a run: engine first, then the broker.

    The engine's resting orders are cancelled by its own teardown, which is
    why the broker has to still be there when it goes.
    """
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    if supervisor.run_id != run_id:
        raise HTTPException(status_code=409,
                            detail="That run is not the one in flight.")

    result = await supervisor.stop()
    run.status = "stopped"
    run.ended_at = datetime.utcnow()
    _audit(db, current_user, "STOP_RUN", str(run_id), str(result))
    db.commit()
    return result


@app.get("/api/v1/runs/{run_id}/log", response_class=PlainTextResponse,
         tags=["Runs"])
def run_log(run_id: int, lines: int = 300, db: Session = Depends(get_db),
            current_user: models.User = Depends(get_current_user)):
    """The run's captured stdout and stderr.

    This is the only place a failure that happened before the engine's status
    API came up is visible at all, which is exactly when you most want it.
    """
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not run.log_path:
        return "This run never got as far as writing a log."
    return (supervisor.tail(lines=max(1, min(lines, 5000)),
                            path=Path(run.log_path))
            or "(log is empty)")


@app.get("/api/v1/supervisor", tags=["Runs"])
def supervisor_state(current_user: models.User = Depends(get_current_user)):
    """What FinHub currently has running, and where CJTrade is."""
    return supervisor.describe()


# ══════════════════════════════════════════════════════════════════════════════
#  Strategies — what somebody wrote in the editor
#
#  Writing a strategy is writing Python that this host will execute. FinHub is
#  a single trust domain: an account on it is permission to run code here, and
#  nothing below pretends otherwise. What these routes do enforce is ownership
#  -- one user cannot read or edit another's source -- and that the checker
#  only ever runs over a bounded amount of text.
# ══════════════════════════════════════════════════════════════════════════════

def _owned_strategy(strategy_id: int, db: Session,
                    user: models.User) -> models.Strategy:
    """Someone else's strategy is reported as missing rather than forbidden.

    A 403 would confirm that strategy 41 exists and belongs to another user,
    which is a thing this endpoint has no reason to tell anyone.
    """
    strategy = db.get(models.Strategy, strategy_id)
    if strategy is None or strategy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return strategy


@app.get("/api/v1/strategies", response_model=list[schemas.StrategySummary],
         tags=["Strategies"])
def list_strategies(db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    return (db.query(models.Strategy)
            .filter(models.Strategy.owner_id == current_user.id)
            .order_by(models.Strategy.updated_at.desc(),
                      models.Strategy.id.desc())
            .all())


@app.get("/api/v1/strategies/api-reference", tags=["Strategies"])
def strategy_api_reference(
        current_user: models.User = Depends(get_current_user)):
    """Every name a strategy may use, for the editor's completion.

    Generated in the CJTrade checkout by introspecting the authoring module, so
    there is no second list to maintain: a function added or removed there
    changes what the editor offers on the next page load. Declared before the
    `/{strategy_id}` route so "api-reference" is not read as an id.
    """
    try:
        return {"entries": strategy_tool.api_reference()}
    except StrategyToolError as exc:
        # The editor is still usable without this -- it falls back to
        # CodeMirror's own Python completion -- so this is not a 500.
        log.warning("could not load the strategy API reference: %s", exc)
        return {"entries": [], "error": TOOL_DOWN}


@app.get("/api/v1/strategies/templates", tags=["Strategies"])
def strategy_templates(current_user: models.User = Depends(get_current_user)):
    """Which starter strategies the editor can offer.

    From the CJTrade checkout, for the same reason the templates themselves
    are: adding one there should change the dropdown here without an edit.
    Declared before `/{strategy_id}` so "templates" is not read as an id.
    """
    try:
        return {"templates": strategy_tool.templates()}
    except StrategyToolError as exc:
        log.warning("could not list the strategy templates: %s", exc)
        return {"templates": [], "error": TOOL_DOWN}


@app.get("/api/v1/strategies/{strategy_id}",
         response_model=schemas.StrategySchema, tags=["Strategies"])
def get_strategy(strategy_id: int, db: Session = Depends(get_db),
                 current_user: models.User = Depends(get_current_user)):
    return _owned_strategy(strategy_id, db, current_user)


@app.post("/api/v1/strategies", response_model=schemas.StrategySchema,
          status_code=201, tags=["Strategies"])
def create_strategy(strategy_in: schemas.StrategyCreateFrom,
                    db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    """Create a strategy, pre-filled unless the caller supplied source.

    The template comes from CJTrade rather than from here, because it is a
    demonstration of CJTrade's authoring API -- if `buy()` grows an argument,
    the file that teaches it should change with it, not a string in FinHub.
    """
    source = strategy_in.source
    if source is None:
        try:
            source = strategy_tool.template(strategy_in.name,
                                            strategy_in.symbol,
                                            kind=strategy_in.kind or "bb")
        except StrategyToolError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    strategy = models.Strategy(
        owner_id=current_user.id, name=strategy_in.name.strip(),
        symbol=strategy_in.symbol.strip().upper(), source=source)
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    _audit(db, current_user, "strategy.create", f"strategy:{strategy.id}",
           f"{strategy.name} ({strategy.symbol})")
    return strategy


@app.put("/api/v1/strategies/{strategy_id}",
         response_model=schemas.StrategySchema, tags=["Strategies"])
def update_strategy(strategy_id: int, patch: schemas.StrategyUpdate,
                    db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    strategy = _owned_strategy(strategy_id, db, current_user)

    if patch.name is not None:
        strategy.name = patch.name.strip()
    if patch.symbol is not None:
        strategy.symbol = patch.symbol.strip().upper()
    if patch.source is not None and patch.source != strategy.source:
        strategy.source = patch.source
        # The stored verdict described the old source. Clearing it is the
        # honest answer until someone checks again -- leaving a green tick on
        # text nobody has checked is worse than showing nothing.
        strategy.last_check_ok = None
        strategy.last_check_error = None

    db.commit()
    db.refresh(strategy)
    return strategy


@app.post("/api/v1/strategies/{strategy_id}/enabled", tags=["Strategies"])
async def set_strategy_enabled(strategy_id: int, payload: schemas.EnabledPatch,
                               db: Session = Depends(get_db),
                               current_user: models.User = Depends(get_current_user)):
    """Switch a strategy on or off, taking effect now.

    Off means two things and both of them matter:

    * it will not be in the next run, and
    * if it is trading *right now*, its bot stops right now.

    The second is the point. Whoever presses this during a paper or real run
    has just found a problem, and "it will not be in the next run" is not an
    answer to that. The engine grew a control plane for it.

    Stopping is not flattening. The bot places no more orders and its resting
    orders are pulled back, and the position it already holds is left exactly
    where it is -- selling it would be a second decision, made at whatever
    price happens to be there, and nobody asked for that by switching a
    strategy off.

    Switching it back on does NOT restart a bot mid-run. The engine builds its
    roster when a run starts, so a re-enabled strategy joins the next one.
    """
    strategy = _owned_strategy(strategy_id, db, current_user)
    was = bool(strategy.enabled)
    strategy.enabled = 1 if payload.enabled else 0
    db.commit()
    db.refresh(strategy)

    result = {"id": strategy.id, "enabled": bool(strategy.enabled),
              "stopped_now": False, "engine": None}

    if was and not payload.enabled:
        bot_id = next((b for b, info in supervisor.bot_strategies.items()
                       if info["strategy_id"] == strategy.id), None)
        if bot_id is not None:
            try:
                result["engine"] = await engine_client.stop_bot(
                    bot_id, f"{strategy.name} was disabled by "
                            f"{current_user.username}")
                result["stopped_now"] = True
                result["bot_id"] = bot_id
            except EngineUnavailable as exc:
                # The flag is already off, so the next run is safe either way.
                # What failed is the urgent half, and saying so is the whole
                # point: somebody who pressed this believes it has stopped.
                log.error("could not stop %s for strategy %d: %s", bot_id,
                          strategy.id, exc)
                result["error"] = (
                    f"{strategy.name} is switched off for the next run, but "
                    f"its bot {bot_id} could NOT be stopped in the run that "
                    f"is going; see FinHub's log for why")

    _audit(db, current_user,
           "strategy.enable" if payload.enabled else "strategy.disable",
           f"strategy:{strategy.id}",
           f"{strategy.name}"
           + (f" — bot {result.get('bot_id')} stopped"
              if result["stopped_now"] else ""))
    db.commit()
    return result


@app.post("/api/v1/strategies/seed-examples", tags=["Strategies"])
def seed_examples(db: Session = Depends(get_db),
                  current_user: models.User = Depends(get_current_user)):
    """Copy the starter strategies into this account.

    Runs once per account automatically (at registration) and can be asked for
    again from the UI. Idempotent per template: a template already present --
    or deleted on purpose -- is not copied again, which is what the
    `examples_seeded` flag on the user is for. Without it, deleting all your
    strategies would have them reappear on the next page load.
    """
    created = _seed_examples_for(db, current_user)
    db.commit()
    return {"created": [{"id": s.id, "name": s.name, "symbol": s.symbol,
                         "kind": s.seeded_from} for s in created]}


# The three the engine's built-in bots run, as editable strategies. Symbols
# match bot_c/bot_a/bot_b so a seeded account mirrors the engine's own roster.
EXAMPLE_STRATEGIES = (
    ("bb", "Bollinger mean reversion", "2317"),
    ("dca", "Monthly DCA", "0050"),
    ("adx", "Regime switch", "2357"),
)


def _seed_examples_for(db: Session, user: models.User) -> list:
    """Write the examples this user does not already have. Does not commit."""
    have = {s.seeded_from for s in
            db.query(models.Strategy)
            .filter(models.Strategy.owner_id == user.id).all()
            if s.seeded_from}
    created = []
    for kind, name, symbol in EXAMPLE_STRATEGIES:
        if kind in have:
            continue
        try:
            source = strategy_tool.template(name, symbol, kind=kind)
        except StrategyToolError as exc:
            # Seeding is a convenience, not a prerequisite. A checkout that
            # cannot produce templates must not stop somebody registering or
            # using the editor.
            log.warning("could not seed the %s example: %s", kind, exc)
            continue
        strategy = models.Strategy(owner_id=user.id, name=name, symbol=symbol,
                                   source=source, seeded_from=kind, enabled=1)
        db.add(strategy)
        created.append(strategy)
    if created:
        db.flush()
    user.examples_seeded = 1
    return created





@app.delete("/api/v1/strategies/{strategy_id}", status_code=204,
            tags=["Strategies"])
def delete_strategy(strategy_id: int, db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    strategy = _owned_strategy(strategy_id, db, current_user)
    name = strategy.name
    db.delete(strategy)
    db.commit()
    _audit(db, current_user, "strategy.delete", f"strategy:{strategy_id}", name)
    return Response(status_code=204)


@app.post("/api/v1/strategies/check", tags=["Strategies"])
def check_strategy(payload: schemas.StrategyCheckRequest,
                   current_user: models.User = Depends(get_current_user)):
    """Diagnostics and declared parameters for source that may not be saved.

    Answers 200 for a file full of errors: "this does not compile" is a
    successful answer to the question asked, and the editor needs the
    diagnostics in the body either way. A 502 means the checker itself could
    not run.
    """
    try:
        return strategy_tool.check(payload.source)
    except StrategyToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/v1/strategies/{strategy_id}/check", tags=["Strategies"])
def check_saved_strategy(strategy_id: int, db: Session = Depends(get_db),
                         current_user: models.User = Depends(get_current_user)):
    """Check what is stored, and remember the verdict.

    Remembered so the list can show which strategies are runnable without
    spawning one subprocess per row.
    """
    strategy = _owned_strategy(strategy_id, db, current_user)
    try:
        result = strategy_tool.check(strategy.source)
    except StrategyToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    errors = [d for d in result.get("diagnostics", [])
              if d.get("severity") != "warning"]
    strategy.last_check_ok = 1 if result.get("ok") else 0
    strategy.last_check_error = (errors[0]["message"][:400] if errors else None)
    db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Audit
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/audit", response_model=list[schemas.AuditLogSchema],
         tags=["Audit"])
def audit_logs(limit: int = 100, db: Session = Depends(get_db),
               current_user: models.User = Depends(get_current_user)):
    return (db.query(models.AuditLog)
            .filter(models.AuditLog.user_id == current_user.id)
            .order_by(models.AuditLog.id.desc())
            .limit(max(1, min(limit, 500))).all())


# ══════════════════════════════════════════════════════════════════════════════
#  SPA fallback. Last, so it cannot shadow a real route.
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/{path_name:path}", response_class=HTMLResponse, tags=["Frontend"])
async def catch_all(path_name: str, request: Request):
    """Serve the shell for a known page so a refresh keeps you where you were.

    An allowlist rather than "anything that is not an API path": a typo should
    be a 404, not a blank dashboard that looks like a bug in the page.
    """
    page = (path_name.strip("/").split("/") or [""])[0]
    if not page or page in PAGES:
        return templates.TemplateResponse(request, "index.html")
    raise HTTPException(status_code=404,
                        detail=f"No page {page!r}. Try: {', '.join(PAGES)}")


def cli(argv=None) -> None:
    """The ``finhub`` command: serve the UI on 127.0.0.1.

    Loopback only, with no option to widen it. The pages are behind FinHub's
    login, but the engine and broker it drives are not authenticated at all;
    to reach FinHub from another machine, forward the port over SSH
    (``ssh -L 8000:127.0.0.1:8000 host``).
    """
    import argparse

    import uvicorn
    from cjtrade.pkgs.logger import setup_logging
    parser = argparse.ArgumentParser(prog="finhub", description="Serve the FinHub web UI on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8000, help="Port on 127.0.0.1 (default 8000).")
    parser.add_argument("--reload", action="store_true",
                        help="Restart when the code changes (development).")
    args = parser.parse_args(argv)
    setup_logging()
    log.info("FinHub on http://127.0.0.1:%d", args.port)
    uvicorn.run(f"{__name__}:app" if args.reload else app, host="127.0.0.1",
                port=args.port, reload=args.reload, log_config=None)
