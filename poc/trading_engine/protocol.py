"""
poc/trading_engine/protocol.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The wire format between the master engine and the bots.

Why this file exists
--------------------
The ZMQ messages used to be hand-rolled dicts with abbreviated keys:

    tick   {"s": "2317", "p": 182.5, "t": 1756...}
    intent {"b_id": "Bot_C", "action": "BUY", "symbol": "2317", "qty": 3, ...}
    fill   {"b_id": ..., "status": "FILLED", "balance": ..., "position": {...}}

Every one of those is a lossy re-invention of something pkgs/models already
defines -- Snapshot, Order, OrderEvent, Position -- so the two ends had to
agree on key spelling by convention, a fill could not say *why* it was not a
fill, and nothing carried a market timestamp you could trust. So the wire now
carries the models themselves, and this module is the only place that knows how
to put a dataclass through msgpack.

What goes on each socket
------------------------
    PUB  tcp://...:5555   topic = symbol     PriceUpdate
    PUB  tcp://...:5555   topic = bot_id     OrderReport
    PUB  tcp://...:5555   topic = __feed__   FeedStatus
    PULL tcp://...:5556                      OrderIntent
    PULL tcp://...:5556                      BotStatus

Five envelopes, because pkgs/models has no type for "a tick plus a sequence
number", "an order event plus the account state it produced", "what a bot and
its strategy currently look like", or "why there are no bars right now".
Everything inside them is a pkgs/models type or a plain scalar.

Codec
-----
`encode` / `decode` round-trip any dataclass listed in `_WIRE_TYPES`, including
nested ones (Order carries a Product; OrderReport carries an OrderEvent).
Dataclasses are tagged on the way out and rebuilt from their own field types on
the way back, so an OrderAction comes back an OrderAction and not the bare
string msgpack would otherwise hand you.
"""
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import get_args
from typing import get_origin
from typing import get_type_hints
from typing import Optional
from typing import Union

import msgpack
from cjtrade.pkgs.models.event import EventType
from cjtrade.pkgs.models.event import FillEvent
from cjtrade.pkgs.models.event import OrderEvent
from cjtrade.pkgs.models.event import TickEvent
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Quote
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.trade import Trade


# ══════════════════════════════════════════════════════════════════════════════
#  Socket addresses.  Here because both ends must agree on them, and this is
#  already the module that defines what agreement means.
# ══════════════════════════════════════════════════════════════════════════════

# Loopback, and not configurable. The master and its bots are one deployment
# unit on one host -- master spawns the bots itself -- so there is no caller on
# another machine to serve. The PULL socket in particular accepts order intents
# and applies no authentication to them, so binding it anywhere wider would let
# anything that can reach this host place orders on the account.
SOCKET_HOST = "127.0.0.1"

# Defaults only; both ends take the port as a parameter so two engines can run
# side by side. They used to be two literals copied into five files, which is
# why the legacy main.py and the new main2.py silently share a port pair while
# speaking incompatible wire formats.
DEFAULT_PRICE_FEED_PORT = 5555     # master PUB  -> bot SUB   (topic = symbol | bot_id | __feed__)
DEFAULT_ORDER_INTENT_PORT = 5556   # bot    PUSH -> master PULL

# Topic every bot subscribes to, for news about the feed itself rather than
# about a symbol or an order. Underscored so it cannot collide with a ticker or
# a bot id: ZMQ SUB matches topics by prefix, and "2317" would also match
# "2317X" if such a symbol ever existed.
FEED_STATUS_TOPIC = "__feed__"


def price_feed_address(port: int = DEFAULT_PRICE_FEED_PORT) -> str:
    """Where master publishes bars and order reports; master binds, bots connect."""
    return f"tcp://{SOCKET_HOST}:{port}"


def order_intent_address(port: int = DEFAULT_ORDER_INTENT_PORT) -> str:
    """Where bots push order intents; master binds, bots connect."""
    return f"tcp://{SOCKET_HOST}:{port}"


# ══════════════════════════════════════════════════════════════════════════════
#  Envelopes — the things that actually travel, and nothing else.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PriceUpdate:
    """One bar for one symbol, published on topic = symbol.

    `seq` counts per symbol, not globally: a bot subscribes to one symbol, so a
    global counter would look full of holes to it and a dropped message would be
    indistinguishable from someone else's tick. Per symbol, a gap means ZMQ
    really did drop a bar on us -- PUB/SUB has no retransmit, so this is the only
    way the bot can find out.

    The market timestamp lives in `snapshot.timestamp`, straight from the broker.
    Under ReplayClock that is the replayed bar time, which is why nothing
    downstream should ever reach for datetime.now().
    """
    seq: int
    snapshot: Snapshot


@dataclass
class OrderIntent:
    """Bot -> master: "I would like this order placed."

    An intent, not an order: the bot never holds a broker session, so what it
    sends is a fully-formed Order that master's ExecutionEngine is free to
    reject. `order.id` is the bot's, and master keeps it, so both ends can talk
    about the same order afterwards.
    """
    bot_id: str
    order: Order
    reason: str = ""


@dataclass
class OrderReport:
    """Master -> bot, published on topic = bot_id.

    One type for all four outcomes -- accepted / filled / cancelled / rejected
    -- because they arrive on one channel and the bot has to tell them apart.
    `event.new_status` is what distinguishes them; OrderEvent.is_filled() and
    friends do the reading.

    `balance` and `position` ride along because the bot's LocalLedgerMirror has
    no other source for them: ExecutionEngine is the only process that holds a
    broker session, so this message *is* the bot's view of its account.

    Not FillEvent: a FillEvent can only describe a PARTIAL or FILLED order, so
    it cannot carry an acceptance or a rejection, and ArenaX fills whole orders
    with no deal id, so its fill_sequence/deal_id fields would be padding. When
    a broker that reports per-deal fills arrives (sinopac's Trade.deals), a
    FillEvent per deal belongs next to this, not instead of it.
    """
    bot_id: str
    event: OrderEvent
    balance: float
    position: Optional[Position] = None


@dataclass
class BotStatus:
    """Bot -> master: what this bot is, and what its strategy is seeing.

    Sent once per bar on the same PUSH socket as OrderIntent. Master is the
    only process that talks to every bot and already holds a broker session,
    so it is the only place these can be collected -- and the collection is
    what a status view, a chart overlay or a stuck-bot alarm all read.

    It is also the heartbeat, deliberately. Master cannot otherwise tell a bot
    that has nothing to say from one that has died or wandered off: a bot that
    outlives its master keeps a stale ledger mirror and goes on placing orders
    against it, which is how a run ends up reporting a negative dropped-bar
    count. One message answers both questions, so the two cannot disagree
    about whether a bot is alive.

    `monitors` is whatever the strategy chose to expose (BaseStrategy.monitors)
    and is therefore not a fixed shape. Put it through wire_safe() before
    sending: a strategy is free to return a numpy scalar, and a monitoring
    field must never be able to kill the trading loop.
    """
    bot_id: str
    seq: int                    # last PriceUpdate.seq this bot saw
    bar_index: int
    market_time: Optional[datetime]
    started_at: datetime
    bars_seen: int
    bars_dropped: int
    # symbol -> short order id. Plain dict, not dict[str, str]: _coerce walks
    # declared field types, and a parametrised generic is not reliably an
    # instance of `type` across Python versions.
    inflight: dict
    balance: float
    monitors: dict


@dataclass
class FeedStatus:
    """Master -> every bot: why there are no bars right now.

    This exists because silence is ambiguous and a bot has to resolve the
    ambiguity pessimistically. A bot that hears nothing cannot tell a dead
    master from a master that is deliberately quiet, and it must assume the
    worst -- a bot acting on a stale ledger mirror is worse than a bot that
    stopped -- so it exits after SILENCE_LIMIT_S.

    That is correct when master has crashed and wrong when master is holding
    the feed because the market is shut, which is two thirds of every weekday
    and all weekend. The two behaviours met in a real paper run: the bot
    started at 01:46, master held the feed, and the bot killed itself 185
    seconds later. Master then published 169 bars, seven hours later, to
    nobody.

    So master says so instead of going quiet. Any message resets the bot's
    silence timer, which is all that is strictly needed; the fields let the bot
    log something more useful than "still waiting".

    Published on FEED_STATUS_TOPIC rather than per bot id, because master does
    not need to know who is listening and a bot that starts later still gets
    the next one.
    """
    market_open: bool
    reason: str
    bars_served: int
    sent_at: datetime


_WIRE_SAFE = (bool, int, float, str)


def wire_safe(values: dict) -> dict:
    """Coerce a strategy's monitors dict to values msgpack can carry.

    Anything numeric becomes a float, anything else becomes its str(). Nothing
    is dropped silently and nothing raises: _encode_hook rejects unregistered
    types with a TypeError, and a monitoring field that can abort a send would
    put the trading loop at the mercy of a display value.

    The pass-through test is on the exact type, not isinstance: np.float64
    subclasses float but msgpack cannot pack it, so a subclass has to go
    through the float()/str() conversion below like any other foreign value.
    """
    out: Dict[str, Any] = {}
    for key, val in values.items():
        name = str(key)
        if val is None or type(val) in _WIRE_SAFE:
            out[name] = val
            continue
        try:
            out[name] = float(val)          # numpy scalars, Decimal, Fraction
            continue
        except (TypeError, ValueError):
            pass
        try:
            out[name] = str(val)
        except Exception:                   # a __str__ that raises
            out[name] = "<unrenderable>"
    return out


def is_resting(status: OrderStatus) -> bool:
    """Does the broker still have this order, with nothing final decided?

    One rule, shared, because master and the bot both branch on it and must not
    disagree: master keeps polling an order while it is resting, and the bot
    holds off re-signalling that symbol while it is resting. If the two had
    separate lists, a status in one list and not the other would either freeze
    the symbol forever or let duplicates through.

    Stated as "still live" rather than "finished" so an unexpected status --
    UNKNOWN, or something a future broker invents -- ends the order instead of
    leaving it in limbo. Being wrongly done is recoverable; being wrongly
    pending is not.
    """
    return status in (OrderStatus.PLACED,
                      OrderStatus.COMMITTED_WAIT_MARKET_OPEN,
                      OrderStatus.COMMITTED_WAIT_MATCHING,
                      OrderStatus.PARTIAL)


def event_type_for(status: OrderStatus) -> EventType:
    """Which EventType an OrderStatus transition should be announced as."""
    return {
        OrderStatus.FILLED: EventType.ORDER_FILLED,
        OrderStatus.PARTIAL: EventType.ORDER_FILLED,
        OrderStatus.CANCELLED: EventType.ORDER_CANCELLED,
        OrderStatus.REJECTED: EventType.ORDER_REJECTED,
    }.get(status, EventType.ORDER_STATUS_CHANGE)


# ══════════════════════════════════════════════════════════════════════════════
#  Codec
# ══════════════════════════════════════════════════════════════════════════════

# Deliberately obscure keys: opt_field and broker_raw_data are free-form dicts
# whose contents we do not control, and a payload that happened to contain a key
# named "type" would be decoded as a model. "__cjt" will not collide by accident.
_TAG = "__cjt"
_VAL = "__v"

_DATETIME_TAG = "datetime"


def _encode_hook(obj: Any) -> Any:
    """Called by msgpack only for values it cannot pack itself."""
    if is_dataclass(obj) and not isinstance(obj, type):
        name = type(obj).__name__
        if name not in _WIRE_TYPES:
            raise TypeError(
                f"{name} is not a registered wire type — add it to _WIRE_TYPES "
                f"in poc/trading_engine/protocol.py, or stop sending it."
            )
        return {_TAG: name,
                _VAL: {f.name: getattr(obj, f.name) for f in fields(obj)}}

    if isinstance(obj, datetime):
        # ISO 8601, naive Asia/Taipei — the one datetime convention this
        # codebase uses at every boundary. No timezone conversion anywhere.
        return {_TAG: _DATETIME_TAG, _VAL: obj.isoformat()}

    if isinstance(obj, Enum):
        # Unreachable for the str-based enums in pkgs/models (msgpack packs a
        # str subclass as a str without consulting us), but a plain Enum would
        # land here.
        return obj.value

    raise TypeError(f"cannot put {type(obj).__name__} on the wire")


def _decode_hook(obj: dict) -> Any:
    """Called by msgpack for every map, innermost first."""
    tag = obj.get(_TAG)
    if tag is None:
        return obj
    if tag == _DATETIME_TAG:
        return datetime.fromisoformat(obj[_VAL])
    cls = _WIRE_TYPES.get(tag)
    if cls is None:
        raise ValueError(f"unknown wire type {tag!r} — version skew between "
                         f"master and bot?")
    return _rebuild(cls, obj[_VAL])


_HINTS: Dict[type, Dict[str, Any]] = {}


def _hints(cls: type) -> Dict[str, Any]:
    """Field types of `cls`, resolved once and remembered.

    get_type_hints() is not cheap and this runs per message per field.
    """
    if cls not in _HINTS:
        _HINTS[cls] = get_type_hints(cls)
    return _HINTS[cls]


def _rebuild(cls: type, values: dict) -> Any:
    hints = _hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name in values:
            kwargs[f.name] = _coerce(hints.get(f.name), values[f.name])
    return cls(**kwargs)


def _coerce(hint: Any, value: Any) -> Any:
    """Put `value` back into the type the field is declared as.

    Only needed for the types msgpack flattens: every enum in pkgs/models
    subclasses str, so it survives the trip as a bare string and has to be
    widened back. Nested dataclasses and datetimes were already rebuilt by the
    object hook before we get here.
    """
    if value is None:
        return None

    if get_origin(hint) is Union:          # Optional[X] -> X
        args = [a for a in get_args(hint) if a is not type(None)]
        hint = args[0] if len(args) == 1 else None

    if isinstance(hint, type):
        if issubclass(hint, Enum):
            return hint(value)
        if hint is datetime and isinstance(value, str):
            return datetime.fromisoformat(value)
        if hint is float and isinstance(value, int):
            return float(value)

    return value


def encode(obj: Any) -> bytes:
    return msgpack.packb(obj, default=_encode_hook, use_bin_type=True)


def decode(buf: bytes) -> Any:
    return msgpack.unpackb(buf, object_hook=_decode_hook,
                           raw=False, strict_map_key=False)


# Everything allowed on the wire. Registered by name, so both processes must
# agree on this list; an unknown name decodes to a clear error instead of a
# silently-wrong dict.
_WIRE_TYPES: Dict[str, type] = {
    cls.__name__: cls
    for cls in (
        # envelopes
        PriceUpdate, OrderIntent, OrderReport, BotStatus, FeedStatus,
        # pkgs/models
        BidAsk, FillEvent, Order, OrderEvent, OrderResult,
        Position, Product, Quote, Snapshot, TickEvent, Trade,
    )
}
