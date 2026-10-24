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
ExecutionEngine (see main.py) — it's the only place that should ever hold a
broker session / touch real money, and it gives every bot's view of balance
one canonical source instead of N independently-simulated ledgers. This bot
only ever *sends* order intents and *mirrors* whatever master reports back;
it never computes balance/position math itself.

This is the shape future bots should follow: users only write a BaseStrategy
subclass (on_start/on_bar/on_fill/on_end); everything below main() is
generic runner plumbing that doesn't change per-strategy.
"""
import logging
import sys
from datetime import datetime

import msgpack
import zmq
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import StrategyContext
from cjtrade.pkgs.strategy.bb import BollingerStrategy

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.bot_c")

# Config
CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

# Must match main.py's ExecutionEngine.INITIAL_BALANCE — the two only need to
# agree before this bot's first fill; after that, master's Fill message is
# authoritative and this bot just overwrites its mirror with it.
INITIAL_BALANCE = 1_000_000.0


class LiveBar:
    """Stand-in for Kbar/_TaggedKbar (engine.py). Master currently only promises
    1m-equivalent granularity (see main.py's Q1/A1 note), so we treat every
    broadcast message as one closed 1m bar directly — no aggregation needed
    here yet. If/when the feed drops to tick granularity, a small candle-builder
    would sit right here, rolling ticks up into 1m bars before this point.
    """
    __slots__ = ("symbol", "timestamp", "open", "high", "low", "close", "volume")

    def __init__(self, symbol: str, price: float, ts: float):
        self.symbol = symbol
        self.timestamp = datetime.fromtimestamp(ts)
        self.open = self.high = self.low = self.close = price
        self.volume = 0


class LocalLedgerMirror:
    """Read-only-ish view of *this bot's* account state, used only to build
    StrategyContext (calc_qty/has_position/equity). It never executes trades —
    it's overwritten wholesale by whatever master's ExecutionEngine reports
    back after a fill/rejection, so it can never drift from the real ledger.
    """

    def __init__(self, balance: float):
        self.balance = balance
        self.positions: dict[str, dict] = {}  # symbol -> {quantity, avg_cost}

    def apply_fill_message(self, msg: dict) -> None:
        self.balance = msg["balance"]
        if msg["qty"] > 0:
            self.positions[msg["symbol"]] = msg["position"]

    def positions_list(self, price_map: dict) -> list[dict]:
        out = []
        for sym, pos in self.positions.items():
            if pos["quantity"] <= 0:
                continue
            price = price_map.get(sym, pos["avg_cost"])
            out.append({
                "symbol": sym,
                "quantity": pos["quantity"],
                "avg_cost": pos["avg_cost"],
                "current_price": price,
                "market_value": price * pos["quantity"],
                "unrealized_pnl": (price - pos["avg_cost"]) * pos["quantity"],
            })
        return out

    def equity(self, price_map: dict) -> float:
        pos_value = sum(
            price_map.get(sym, p["avg_cost"]) * p["quantity"]
            for sym, p in self.positions.items() if p["quantity"] > 0
        )
        return self.balance + pos_value


def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    target_symbol = "BTCUSDT"

    strategy = BollingerStrategy()
    ledger = LocalLedgerMirror(INITIAL_BALANCE)
    price_map: dict[str, float] = {}
    price_history: dict[str, list] = {}
    params: dict = {}

    log.info(f"[{bot_id}] started! ({target_symbol}) strategy={strategy.name}")

    zmq_context = zmq.Context()
    sub_socket = zmq_context.socket(zmq.SUB)
    sub_socket.connect(CJ_ENGINE_SOCKET_SUB_PRICE)
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))
    # Fill/rejection confirmations from master are published on our own bot_id
    # topic (see main.py's handle_orders) — subscribe to that too, same socket.
    sub_socket.set(zmq.SUBSCRIBE, bot_id.encode('utf-8'))

    push_socket = zmq_context.socket(zmq.PUSH)
    push_socket.connect(CJ_ENGINE_SOCKET_PUSH_STATE)

    strategy.on_start(StrategyContext(
        timestamp=datetime.now(), balance=ledger.balance, equity=ledger.balance,
        positions=[], price_history={}, bar_index=0, params=params,
    ))

    bar_index = 0
    try:
        while True:
            topic, payload = sub_socket.recv_multipart()
            data = msgpack.unpackb(payload)

            if topic == bot_id.encode('utf-8'):
                # This is a Fill/Rejection addressed to us, not a price bar.
                ledger.apply_fill_message(data)
                if data["status"] != "FILLED":
                    log.debug(f"[{bot_id}] order rejected: {data.get('reason')}")
                    continue
                fill = Fill(symbol=data["symbol"], action=data["action"], quantity=data["qty"],
                            price=data["price"], timestamp=datetime.fromtimestamp(data["t"]),
                            reason=data.get("reason", ""))
                ctx = StrategyContext(
                    timestamp=fill.timestamp, balance=ledger.balance, equity=ledger.equity(price_map),
                    positions=ledger.positions_list(price_map), price_history=price_history,
                    bar_index=bar_index, params=params,
                )
                strategy.on_fill(fill, ctx)
                continue

            # Otherwise it's a price bar for our target symbol.
            bar = LiveBar(data["s"], data["p"], data["t"])
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
                # Just the intent — master's ExecutionEngine decides if/how it fills.
                order = {"b_id": bot_id, "action": sig.action, "symbol": sig.symbol,
                         "qty": sig.quantity, "price": sig.price, "reason": sig.reason,
                         "t": data["t"]}
                push_socket.send(msgpack.packb(order))

    except KeyboardInterrupt:
        strategy.on_end(StrategyContext(
            timestamp=datetime.now(), balance=ledger.balance,
            equity=ledger.equity(price_map), positions=ledger.positions_list(price_map),
            price_history=price_history, bar_index=bar_index, params=params,
        ))
        log.info(f"[{bot_id}] exited without error (balance={ledger.balance:.0f})")


if __name__ == "__main__":
    main()
