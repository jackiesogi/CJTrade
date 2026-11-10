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

The Snapshot becomes a Kbar via Kbar.from_snapshot(), which is the same type
BacktestEngine feeds a strategy — so a strategy cannot tell the two runners
apart.

This is the shape future bots should follow: users only write a BaseStrategy
subclass (on_start/on_bar/on_fill/on_end); everything below main() is
generic runner plumbing that doesn't change per-strategy.
"""
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import protocol
import zmq
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import StrategyContext
from cjtrade.pkgs.strategy.bb import BollingerStrategy
from protocol import BotStatus
from protocol import OrderIntent
from protocol import OrderReport
from protocol import PriceUpdate

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.bot_c")

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

# How long to sit on a silent socket before concluding master is gone.
#
# In seconds rather than bars because the two clocks are three orders of
# magnitude apart: under ReplayClock a bar lands every ~12ms, under
# RealtimeClock every 60s. 180s is three missed live bars, and master's long
# startup work (kbar fetch, preload) happens before it spawns anyone, so a
# healthy bot is never silent that long.
#
# Without this a bot blocks in recv forever. One that outlives its master keeps
# a stale ledger mirror and goes on trading against it, and because it is still
# subscribed to the same port the next master's bars arrive with a sequence
# number lower than its own -- which showed up as a negative dropped-bar count.
RECV_TIMEOUT_MS = 5000
SILENCE_LIMIT_S = 180.0


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


def build_order(bot_id: str, session_id: str, sig, bar: Kbar) -> Order:
    """Turn a strategy Signal into the Order master should place.

    The Order is fully formed here, including its id: master places it with that
    id, so the OrderReport that comes back later is unambiguously about this
    signal. created_at is the bar's market time, not datetime.now(), so a replay
    run stamps orders with replayed time.

    session_id rides in opt_field because the ArenaX backend copies it into
    fill_history when it settles a fill (base_backend._apply_fill), which is how
    master's end-of-run report asks for this run's trades and not the ones
    sitting on the server from a previous run.
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
        opt_field={"bot_id": bot_id, "session_id": session_id},
    )


def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    # argv[2] is master's starting balance. Taking it from master rather than
    # keeping a local constant means the two cannot disagree: the mirror only
    # matters until this bot's first fill, but position sizing before that fill
    # would be computed against the wrong equity.
    initial_balance = float(sys.argv[2]) if len(sys.argv) > 2 else INITIAL_BALANCE
    # argv[3] is master's session id. Empty when launched by the legacy main.py,
    # which does not report on a run and so has nothing to filter by.
    session_id = sys.argv[3] if len(sys.argv) > 3 else ""
    target_symbol = "2317"

    strategy = BollingerStrategy()
    ledger = LocalLedgerMirror(initial_balance)
    price_map: dict[str, float] = {}
    price_history: dict[str, list] = {}
    params: dict = {
        # "bb__min_width_pct": 0.001
        "bb__min_width_pct": 0.01,
        "bb__window_size": 100,
        # Fraction of equity per position, read by calc_qty (base_strategy.py).
        # The strategy's own default is 0.05, which against the backtest
        # backend's 100,000 account sizes a 20-share order -- and commission is
        # max(notional * 0.1425%, NT$20), so 20 shares pay the NT$20 floor:
        # 1.100% of notional round trip instead of the statutory 0.585%. The
        # floor stops biting at 57 shares (notional 14,035), so 0.20 -> 80
        # shares buys the whole of that saving.
        #
        # It does not make this strategy profitable. 0.585% is the floor from
        # 0.1425% commission twice plus 0.3% transaction tax, and a one-tick
        # target on a 250 stock is 0.4%. Size fixes the penalty, not the edge.
        "risk__max_position_pct": 0.20,
    }

    log.info(f"[{bot_id}] started! ({target_symbol}) strategy={strategy.name}")

    started_at = datetime.now()

    zmq_context = zmq.Context()
    sub_socket = zmq_context.socket(zmq.SUB)
    sub_socket.connect(protocol.price_feed_address())
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))
    # Order reports from master are published on our own bot_id topic (see
    # main2.py's publish_report) — subscribe to that too, same socket.
    sub_socket.set(zmq.SUBSCRIBE, bot_id.encode('utf-8'))
    # So recv can return instead of blocking forever; see SILENCE_LIMIT_S.
    sub_socket.set(zmq.RCVTIMEO, RECV_TIMEOUT_MS)

    push_socket = zmq_context.socket(zmq.PUSH)
    push_socket.connect(protocol.order_intent_address())

    # master terminates bots with SIGTERM, which Python does not turn into an
    # exception, so the shutdown path below never ran on a normal end of run --
    # on_end was only ever reached by Ctrl-C. Convert it, so a bot reports its
    # final state however the run ends.
    def _on_sigterm(_sig, _frm):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _on_sigterm)

    strategy.on_start(StrategyContext(
        timestamp=datetime.now(), balance=ledger.balance, equity=ledger.balance,
        positions=[], price_history={}, bar_index=0, params=params,
    ))

    bar_index = 0
    last_seq = -1
    bars_dropped = 0
    inflight: dict[str, InFlight] = {}
    silent_since: float | None = None
    try:
        while True:
            try:
                _topic, payload = sub_socket.recv_multipart()
            except zmq.Again:
                # Nothing from master this interval. Any traffic at all resets
                # this, including an order report, so only a genuinely dead
                # master accumulates silence.
                now = time.monotonic()
                if silent_since is None:
                    silent_since = now
                elif now - silent_since >= SILENCE_LIMIT_S:
                    log.error(f"[{bot_id}] nothing from master for "
                              f"{now - silent_since:.0f}s — assuming it is gone "
                              f"and exiting rather than trading on a stale mirror")
                    break
                continue
            silent_since = None
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
                missed = msg.seq - last_seq - 1
                if missed < 0:
                    # Not a drop: a sequence that went backwards means these
                    # bars are from a different master than the last ones, i.e.
                    # this bot outlived its own. SILENCE_LIMIT_S should have
                    # caught that first, so say so loudly and stop.
                    log.error(f"[{bot_id}] sequence went backwards "
                              f"({last_seq} -> {msg.seq}) — these bars belong to "
                              f"another master. Exiting.")
                    break
                bars_dropped += missed
                log.warning(f"[{bot_id}] dropped {missed} bar(s) "
                            f"of {target_symbol} (seq {last_seq} -> {msg.seq})")
            last_seq = msg.seq

            # One broadcast = one closed bar. Master promises 1m-equivalent
            # granularity (see main.py's Q1/A1 note); if the feed ever drops to
            # tick granularity, a candle-builder belongs right here.
            bar = Kbar.from_snapshot(msg.snapshot)
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
                order = build_order(bot_id, session_id, sig, bar)
                inflight[sig.symbol] = InFlight(order_id=order.id, bar_sent=bar_index)
                push_socket.send(protocol.encode(
                    OrderIntent(bot_id=bot_id, order=order, reason=sig.reason)
                ))

            # After the signals, so the status reflects the orders this bar
            # produced rather than the state just before them.
            push_socket.send(protocol.encode(BotStatus(
                bot_id=bot_id,
                seq=last_seq,
                bar_index=bar_index,
                market_time=bar.timestamp,
                started_at=started_at,
                bars_seen=bar_index,
                bars_dropped=bars_dropped,
                inflight={s: f.order_id[:8] for s, f in inflight.items()},
                balance=ledger.balance,
                monitors=protocol.wire_safe(strategy.monitors()),
            )))

    except KeyboardInterrupt:
        pass

    # One shutdown path for every exit: Ctrl-C, SIGTERM from master, a dead
    # master, or a sequence from someone else's master.
    strategy.on_end(StrategyContext(
        timestamp=datetime.now(), balance=ledger.balance,
        equity=ledger.equity(price_map), positions=ledger.positions_list(price_map),
        price_history=price_history, bar_index=bar_index, params=params,
    ))
    mon = strategy.monitors()
    log.info(f"[{bot_id}] exiting after {bar_index} bar(s), "
             f"balance={ledger.balance:.0f}, dropped={bars_dropped}"
             + (f", {mon.get('signals_emitted', '?')} signal(s)" if mon else ""))
    if mon:
        log.info(f"[{bot_id}] final monitors: "
                 + "  ".join(f"{k}={v}" for k, v in mon.items()))


if __name__ == "__main__":
    main()
