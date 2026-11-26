"""What FinHub itself stores.

Deliberately small. FinHub is a front end: the authority on an account is the
broker and the authority on a run in flight is the engine, so copying either
into this database would only create a second answer that can disagree. What
lives here is what nothing else keeps:

* `Run`     -- that a run happened, how it was configured, and how it ended.
              The engine forgets a run the moment its process exits.
* `BotSlot` -- which strategy was asked to run under which bot id.
* `ManualOrder` -- that a human, not a bot, placed this order. The broker
              records the order but not who asked for it, and the engine's
              risk gate never saw it.
* `Strategy` -- source somebody wrote in the editor. Nothing else keeps it:
              the engine is handed a file and forgets it when the run ends.
"""
from datetime import datetime

from cjtrade.apps.FinHub.database import Base
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    # Whether the starter strategies have been copied into this account.
    # A flag rather than "seed when they have none", so deleting all of them
    # is a decision that sticks instead of being undone on the next request.
    examples_seeded = Column(Integer, default=0, nullable=False)

    runs = relationship("Run", back_populates="owner",
                        cascade="all, delete-orphan")
    manual_orders = relationship("ManualOrder", back_populates="owner",
                                 cascade="all, delete-orphan")
    strategies = relationship("Strategy", back_populates="owner",
                              cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user_ref")


class Run(Base):
    """One engine run, from launch to teardown.

    `session_id` is the engine's own uuid, stamped on every order the bots
    place, which is how this row can be matched against the broker's fill
    history afterwards. It is null until the engine logs it, because FinHub
    starts the process and only then learns what session it chose.
    """
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    # Configuration, exactly as handed to the engine.
    broker = Column(String, default="arenax")
    mode = Column(String, default="backtest")       # backtest | paper | demo
    symbols = Column(String, default="")            # comma separated
    days = Column(Integer, default=20)
    fund = Column(Float, default=1_000_000.0)
    speed = Column(Float, default=1.0)
    start_date = Column(String, default="")         # "" == let the server pick
    # What one bar was for this run. Recorded because it changes what the
    # strategy saw -- a 100-bar window is 100 minutes at 1m and 100 sessions
    # at 1d -- so two runs are not comparable without it.
    interval = Column(String, default="1m")         # 1m|5m|15m|30m|1h|1d
    arenax_port = Column(Integer, default=8802)
    status_port = Column(Integer, default=8898)

    # starting | running | finished | failed | stopped
    status = Column(String, default="starting", index=True)
    exit_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    log_path = Column(String, nullable=True)

    started_at = Column(DateTime, default=func.now())
    ended_at = Column(DateTime, nullable=True)

    # Filled in at teardown from the engine's last reported state, so the runs
    # list means something without the engine still being alive.
    bars_served = Column(Integer, nullable=True)
    final_equity = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    fills = Column(Integer, nullable=True)
    round_trips = Column(Integer, nullable=True)
    win_rate = Column(Float, nullable=True)
    halt_reason = Column(String, nullable=True)

    owner = relationship("User", back_populates="runs")
    bot_slots = relationship("BotSlot", back_populates="run",
                             cascade="all, delete-orphan")


class BotSlot(Base):
    """Which strategy a bot id was asked to run, for one run.

    The engine reports a bot's live state but not what it was *meant* to be;
    today it spawns one hardcoded Bot_C. This table is what lets the UI label
    bots by strategy as soon as the engine takes more than one.
    """
    __tablename__ = "bot_slots"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"))
    bot_id = Column(String, index=True)
    # The strategy's name as it was at launch, kept as text so a run stays
    # readable after the strategy is renamed or deleted.
    strategy = Column(String, default="")
    symbol = Column(String, default="")
    # Which saved strategy this was, when it was one. Null for the built-in
    # bots, and nulled again if the strategy is later deleted -- the row is the
    # record that a run happened, so it must outlive the source it ran.
    strategy_id = Column(Integer,
                         ForeignKey("strategies.id", ondelete="SET NULL"),
                         nullable=True, index=True)

    run = relationship("Run", back_populates="bot_slots")
    strategy_ref = relationship("Strategy", back_populates="bot_slots")


class ManualOrder(Base):
    """An order a human placed from the Trade page.

    Recorded here because neither of the other two systems knows this fact:
    the broker sees an order like any other, and the engine's RiskGate never
    sees it at all. Without this row a manual order is indistinguishable from
    a bot's in the fill history, which makes a run's numbers unexplainable.
    """
    __tablename__ = "manual_orders"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="SET NULL"),
                    nullable=True)

    order_id = Column(String, index=True)       # the broker's / our uuid
    symbol = Column(String, index=True)
    action = Column(String)                     # BUY | SELL
    quantity = Column(Integer)
    price = Column(Float)
    order_lot = Column(String)                  # Common | IntraDayOdd
    status = Column(String)                     # as the broker answered
    message = Column(String, default="")
    created_at = Column(DateTime, default=func.now())

    owner = relationship("User", back_populates="manual_orders")


class AuditLog(Base):
    """Permanent trail of the operations that change something.

    Starting a run, stopping a run, placing an order, cancelling everything.
    Reads are not logged -- a log nobody can read through is not a trail.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    target = Column(String, default="")
    details = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)

    user_ref = relationship("User", back_populates="audit_logs")


class Strategy(Base):
    """Source somebody wrote in the editor, and which symbol it is for.

    Here rather than as a file on disk because a strategy belongs to a user and
    the filesystem has no opinion about that. The engine does get a file -- the
    supervisor writes one out when a run starts -- but that file is a copy made
    for one run, not the record.

    `symbol` is part of the strategy rather than part of the run: a strategy
    written against a 50-cent ETF and one written against a 1,000-dollar
    semiconductor are not the same strategy with a different argument, and
    pretending otherwise is how thresholds end up meaning nothing (see the ADX
    measurement in CJTrade's adx.py).
    """
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String, index=True)
    symbol = Column(String, default="", index=True)
    source = Column(Text, default="")
    # Last thing the checker said about this source. Stored so the list can
    # show which strategies are runnable without re-checking every one of
    # them -- each check is a subprocess in the CJTrade checkout.
    last_check_ok = Column(Integer, nullable=True)      # 1 | 0 | null = never
    last_check_error = Column(String, nullable=True)
    # Whether this strategy trades. Switching it off during a run stops its
    # bot there and then -- the engine has a control plane for exactly this,
    # because "it will not be in the next run" is no answer to finding a
    # problem while money is moving. Switching it off between runs keeps it
    # out of the next one.
    #
    # 1/0 rather than Boolean to match last_check_ok, which SQLite stores the
    # same way anyway. Defaults to on: a strategy somebody just wrote and
    # checked should run.
    enabled = Column(Integer, default=1, nullable=False)
    # Which template it started from, when it started from one. Kept so the
    # examples can be seeded once and not re-seeded after being deleted.
    seeded_from = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="strategies")
    # Not a delete cascade: deleting a strategy takes it off the bots page but
    # must not erase the record of the runs that used it. SQLAlchemy nulls the
    # child's strategy_id, which is what leaves a past bot labelled by the
    # name recorded in BotSlot.strategy.
    bot_slots = relationship("BotSlot", back_populates="strategy_ref")
