"""
poc/trading_engine/bot_c.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Same market-data plumbing as bot_a.py / bot_b.py (SUB price feed, PUSH to
master), but instead of a hand-rolled if-price>X check, it drives a real
BaseStrategy subclass (BollingerStrategy from pkgs/strategy/bb.py) the same
way BacktestEngine.run() does — just event-driven per broadcast message
instead of looping over a pre-fetched kbar list. See engine.py's `run()` for
the reference this loop is modeled on.

This bot does NOT execute its own trades. Order execution moved to master's
ExecutionEngine (see main2.py) — it's the only place that should ever hold a
broker session / touch real money, and it gives every bot's view of balance
one canonical source instead of N independently-simulated ledgers. This bot
only ever *sends* order intents and *mirrors* whatever master reports back;
it never computes balance/position math itself.

Everything on the wire is a pkgs/models type (see protocol.py): price bars
arrive as a Snapshot, order intents go out as an Order, and master answers with
an OrderEvent. So an "order rejected" and an "order accepted, still resting"
are different messages here rather than the same one, which is what lets the
mirror stay in step with master's ledger.

This is the shape future bots should follow: users only write a BaseStrategy
subclass (on_start/on_bar/on_fill/on_end); everything below main() is
generic runner plumbing that doesn't change per-strategy.
"""
import logging
import sys
from dataclasses import dataclass
from datetime import datetime

import protocol
import zmq
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import StrategyContext
from cjtrade.pkgs.strategy.bb import BollingerStrategy
from protocol import OrderIntent
from protocol import OrderReport
from protocol import PriceUpdate

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.bot_c")

# Config
CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

# Fallback only — master normally passes the broker's starting balance as
# argv[2] (main2.py). Used when this script is run standalone. The mirror only
# matters before this bot's first report; after that master's OrderReport is
# authoritative and this bot overwrites its mirror with whatever master reports.
INITIAL_BALANCE = 1_000_000.0

# How many bars to wait for master's FIRST word about an order before deciding
# the conversation was lost and trading that symbol again.
#
# Only the first word. Once master has said anything about the order -- even
# just "accepted, resting" -- it is in its _open map and will keep polling until
# the order resolves, so there is no deadline to enforce: a limit order can
# legitimately rest for hundreds of bars waiting for the price to come to it.
# The deadline is for silence, which means a lost intent on the PUSH socket or a
# lost report on the PUB socket; neither is retransmitted, and without a
# deadline either one would freeze this symbol for the rest of the run.
UNACKED_MAX_BARS = 10


class LiveBar:
    """Stand-in for Kbar/_TaggedKbar (engine.py), built from a Snapshot.

    Master promises 1m-equivalent granularity (see main.py's Q1/A1 note), so
    every broadcast is treated as one closed 1m bar. The OHLC is the broker's
    own, not open=high=low=close as it was when the feed only carried a close
    price. If/when the feed drops to tick granularity, a small candle-builder
    would sit right here, rolling ticks up into 1m bars before this point.
    """
    __slots__ = ("symbol", "timestamp", "open", "high", "low", "close", "volume")

    def __init__(self, snap: Snapshot):
        self.symbol = snap.symbol
        self.timestamp = snap.timestamp
        self.open = snap.open
        self.high = snap.high
        self.low = snap.low
        self.close = snap.close
        self.volume = snap.volume


class LocalLedgerMirror:
    """Read-only-ish view of *this bot's* account state, used only to build
    StrategyContext (calc_qty/has_position/equity). It never executes trades —
    it's overwritten wholesale by whatever master's ExecutionEngine reports
    back in an OrderReport, so it can never drift from the real ledger.
    """

    def __init__(self, balance: float):
        self.balance = balance
        self.positions: dict[str, Position] = {}

    def apply(self, report: OrderReport) -> None:
        """Take master's numbers verbatim. Compute nothing.

        Applied for every report, including rejections: a rejection still tells
        us master's current balance, and in the resting case it is the only
        thing that will.
        """
        self.balance = report.balance
        symbol = report.event.symbol
        if report.position is not None:
            self.positions[symbol] = report.position
        else:
            # Master says there is no position in this symbol any more.
            self.positions.pop(symbol, None)

    def positions_list(self, price_map: dict) -> list[dict]:
        """StrategyContext.positions wants dicts — Position.to_dict() has
        exactly the keys it documents, so mark the position to market and let
        the model do the spelling."""
        out = []
        for sym, pos in self.positions.items():
            if pos.quantity <= 0:
                continue
            pos.current_price = price_map.get(sym, pos.avg_cost)
            pos.market_value = pos.current_price * pos.quantity
            pos.unrealized_pnl = (pos.current_price - pos.avg_cost) * pos.quantity
            out.append(pos.to_dict())
        return out

    def equity(self, price_map: dict) -> float:
        pos_value = sum(
            price_map.get(sym, p.avg_cost) * p.quantity
            for sym, p in self.positions.items() if p.quantity > 0
        )
        return self.balance + pos_value


@dataclass
class InFlight:
    """An order this bot has sent that master has not resolved yet.

    A strategy sees positions, not orders. While a SELL rests at the broker the
    position is still on the books, so the same upper-band touch fires again on
    the next bar and the bot submits a duplicate the broker can only reject --
    which is exactly what the log showed once acceptance stopped being reported
    as rejection. Holding one in-flight order per symbol stops that.
    """
    order_id: str
    bar_sent: int
    acknowledged: bool = False   # master has said *something* about this order


def build_order(bot_id: str, sig, bar: LiveBar) -> Order:
    """Turn a strategy Signal into the Order master should place.

    The Order is fully formed here, including its id: master places it with that
    id, so the OrderReport that comes back later is unambiguously about this
    signal. created_at is the bar's market time, not datetime.now(), so a replay
    run stamps orders with replayed time.
    """
    return Order(
        product=Product(symbol=sig.symbol),
        action=OrderAction(sig.action),
        price=float(sig.price),
        quantity=int(sig.quantity),
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.IntraDayOdd,
        created_at=bar.timestamp,
        opt_field={"bot_id": bot_id},
    )


def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    # argv[2] is master's starting balance. Taking it from master rather than
    # keeping a local constant means the two cannot disagree: the mirror only
    # matters until this bot's first fill, but position sizing before that fill
    # would be computed against the wrong equity.
    initial_balance = float(sys.argv[2]) if len(sys.argv) > 2 else INITIAL_BALANCE
    target_symbol = "2317"

    strategy = BollingerStrategy()
    ledger = LocalLedgerMirror(initial_balance)
    price_map: dict[str, float] = {}
    price_history: dict[str, list] = {}
    params: dict = {
        "bb__min_width_pct": 0.001
    }

    log.info(f"[{bot_id}] started! ({target_symbol}) strategy={strategy.name}")

    zmq_context = zmq.Context()
    sub_socket = zmq_context.socket(zmq.SUB)
    sub_socket.connect(CJ_ENGINE_SOCKET_SUB_PRICE)
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))
    # Order reports from master are published on our own bot_id topic (see
    # main2.py's publish_report) — subscribe to that too, same socket.
    sub_socket.set(zmq.SUBSCRIBE, bot_id.encode('utf-8'))

    push_socket = zmq_context.socket(zmq.PUSH)
    push_socket.connect(CJ_ENGINE_SOCKET_PUSH_STATE)

    strategy.on_start(StrategyContext(
        timestamp=datetime.now(), balance=ledger.balance, equity=ledger.balance,
        positions=[], price_history={}, bar_index=0, params=params,
    ))

    bar_index = 0
    last_seq = -1
    inflight: dict[str, InFlight] = {}
    try:
        while True:
            _topic, payload = sub_socket.recv_multipart()
            msg = protocol.decode(payload)

            if isinstance(msg, OrderReport):
                ledger.apply(msg)
                event = msg.event

                held = inflight.get(event.symbol)
                if held is not None and held.order_id == event.order_id:
                    if protocol.is_resting(event.new_status):
                        # Still live and still spending the balance, but master
                        # is now tracking it, so stop counting bars.
                        held.acknowledged = True
                    else:
                        # Resolved — the symbol is free to trade again.
                        del inflight[event.symbol]

                if event.is_filled():
                    fill = Fill(
                        symbol=event.symbol, action=event.action.value,
                        quantity=event.filled_quantity, price=event.filled_price,
                        timestamp=event.timestamp, reason=event.message,
                    )
                    ctx = StrategyContext(
                        timestamp=fill.timestamp, balance=ledger.balance,
                        equity=ledger.equity(price_map),
                        positions=ledger.positions_list(price_map),
                        price_history=price_history, bar_index=bar_index,
                        params=params,
                    )
                    strategy.on_fill(fill, ctx)
                elif protocol.is_resting(event.new_status):
                    # Accepted and resting at the broker. NOT a rejection: the
                    # cash is already committed, and a fill will be reported on
                    # a later bar once the price crosses.
                    log.info(f"[{bot_id}] order {event.order_id[:8]} resting "
                             f"({event.new_status.value}) — "
                             f"{event.action.value} {event.symbol} "
                             f"x{event.quantity} @ {event.price}")
                else:
                    log.info(f"[{bot_id}] order {event.order_id[:8]} "
                             f"{event.new_status.value}: {event.message}")
                continue

            if not isinstance(msg, PriceUpdate):
                log.warning(f"[{bot_id}] ignoring unexpected message "
                            f"{type(msg).__name__}")
                continue

            # PUB/SUB has no retransmit, so a gap in the per-symbol sequence is
            # the only evidence that a bar never reached us. Worth saying out
            # loud: the strategy's price history now has a hole in it.
            if last_seq >= 0 and msg.seq != last_seq + 1:
                log.warning(f"[{bot_id}] dropped {msg.seq - last_seq - 1} bar(s) "
                            f"of {target_symbol} (seq {last_seq} -> {msg.seq})")
            last_seq = msg.seq

            bar = LiveBar(msg.snapshot)
            price_map[bar.symbol] = bar.close
            price_history.setdefault(bar.symbol, []).append(bar.close)

            ctx = StrategyContext(
                timestamp=bar.timestamp,
                balance=ledger.balance,
                equity=ledger.equity(price_map),
                positions=ledger.positions_list(price_map),
                price_history=price_history,  # direct reference, same as engine.py
                bar_index=bar_index,
                params=params,
            )
            bar_index += 1

            for sig in strategy.on_bar(bar, ctx) or []:
                if sig.action not in ("BUY", "SELL"):
                    continue

                held = inflight.get(sig.symbol)
                if held is not None:
                    waited = bar_index - held.bar_sent
                    if held.acknowledged or waited < UNACKED_MAX_BARS:
                        log.debug(f"[{bot_id}] skipping {sig.action} {sig.symbol}: "
                                  f"order {held.order_id[:8]} still in flight")
                        continue
                    log.warning(f"[{bot_id}] no word on order "
                                f"{held.order_id[:8]} after {waited} bars — "
                                f"assuming it never reached master, trading "
                                f"{sig.symbol} again")

                # Just the intent — master's ExecutionEngine decides if/how it fills.
                order = build_order(bot_id, sig, bar)
                inflight[sig.symbol] = InFlight(order_id=order.id, bar_sent=bar_index)
                push_socket.send(protocol.encode(
                    OrderIntent(bot_id=bot_id, order=order, reason=sig.reason)
                ))

    except KeyboardInterrupt:
        strategy.on_end(StrategyContext(
            timestamp=datetime.now(), balance=ledger.balance,
            equity=ledger.equity(price_map), positions=ledger.positions_list(price_map),
            price_history=price_history, bar_index=bar_index, params=params,
        ))
        log.info(f"[{bot_id}] exited without error (balance={ledger.balance:.0f})")


if __name__ == "__main__":
    main()
