import asyncio
import logging
import random
import sys
import time
from pathlib import Path

import msgpack
import zmq.asyncio
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.product import Product

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.trading_engine")

# This name is from bot's point-of-view
CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

BOT_A_SCRIPT = Path(__file__).resolve().parent / "bot_a.py"
BOT_B_SCRIPT = Path(__file__).resolve().parent / "bot_b.py"
BOT_C_SCRIPT = Path(__file__).resolve().parent / "bot_c.py"

# Paper-mode starting balance for ExecutionEngine's per-bot ledger. bot_c.py has
# the same constant for its local mirror — the two only ever need to agree
# before a bot's first fill; after that, master's Fill message is authoritative
# and the bot just overwrites its mirror with whatever master reports.
INITIAL_BALANCE = 1_000_000.0

### Q1: 如果未來 support 除了 1m kbar 以外的時間尺度，Trading Engine 的工作要負責
###     先做好 aggregation 再 broadcast 出去嗎（變成 broadcast 出去的 payload 也
###     要包含 interval 這種欄位）？
### A1: 我目前的想法是讓 bot 自己做 aggregation 因為畢竟 context （例如近 100 筆
###     kbar data）本來就是 bot 自行維護的（？）所以 Engine 只要負責廣播 1m 的就好
###     不過這也會有一個問題，也就是之後如果需要 scale 到更高頻的時間尺度（例如 tick）
###     會有點不知道要怎麼設計比較好。
### 決定：維持 A1，bot 自己 aggregate。Engine 只保證「廣播它手上最小的顆粒度」，
###     不負責幫每個 bot 各自想要的 timeframe 做預先聚合 —— 不同 bot 可能同時要
###     1m/5m/tick 等不同尺度，讓 Engine 幫全部人做等於要它認識所有 strategy 的需求，
###     破壞 Engine 不理解 strategy 的邊界。之後真的要做到 tick 級時，聚合器應該是
###     bot 端的一個小元件（收到 tick → 累積成使用者要的 bar → 再丟進 on_bar），
###     而不是塞進 Engine。bot_c.py 的 LiveBar 已經預留了這個位置的註解。
class EventHub:
    def __init__(self, account_client: AccountClient, playback_speed: float):
        self.client = account_client
        self.playback_speed = playback_speed
        # self.playback_speed = 120.0
        self.watch_list = set()
        self.pub_socket = None
        self._last_price: dict[str, float] = {}

    async def _broadcast(self, tick: dict):
        symbol = tick["s"]
        payload = msgpack.packb(tick)
        # Send multipart: [Topic, Data]，same with bot.py per-symbol topic filtering.
        await self.pub_socket.send_multipart([symbol.encode('utf-8'), payload])
        log.debug(f"[Master] Broadcasting {symbol} at {tick['p']}...")

    def _snapshot(self, symbol: str) -> dict:
        if self.client is not None:
            return self._snapshot_real(symbol)
        return self._snapshot_mock(symbol)

    def _snapshot_real(self, symbol: str) -> dict:
        # get_snapshots() takes a List[Product], but ArenaXBrokerAPI_v2's own
        # implementation just loops over it and calls the single-symbol
        # middleware.snapshot() endpoint per product anyway (no real batch
        # endpoint) — so passing one symbol at a time costs zero extra round
        # trips here, and keeps this the same shape as the mock path below.
        snap = self.client.get_snapshots([Product(symbol=symbol)])[0]
        return {"s": snap.symbol, "p": snap.close, "t": snap.timestamp.timestamp()}

    # Paper-mode fallback (account_client=None) — bounded random walk.
    def _snapshot_mock(self, symbol: str) -> dict:
        # Bounded random WALK (not iid uniform draws) — a strategy like BB needs
        # actual momentum/autocorrelation between ticks for price to ever wander
        # past its rolling bands. Pure iid uniform(90,110) noise never does that
        # (single-sample deviation is capped at 10, tighter than the ~11.5-wide
        # 2-sigma band that distribution produces), so BB would never fire.
        prev = self._last_price.get(symbol, 100.0)
        price = max(50.0, min(200.0, prev + random.gauss(0, 1.2)))
        self._last_price[symbol] = price
        return {"s": symbol, "p": round(price, 2), "t": time.time()}

    # we will trigger _reload_loop every 60 / playback_speed second
    # and in each reload loop, broadcast the kbar price feed.
    # the bot themselves will filter their data of interest.
    #
    # 這裡選擇「一次 snapshot 就一次 broadcast」：watch_list 內每個 symbol 各自
    # snapshot 完立刻送出，而不是全部 symbol 湊成一包再一次送出。原因是 bot.py
    # 訂閱端是用 ZMQ topic (symbol) 做過濾，PUB/SUB 本來就是一則訊息對一個 topic，
    # 沒有「一包多 symbol」的合併訊息格式。曾經想過改成「一次呼叫 get_snapshots
    # 拿多個 symbol、批次查詢」，但查了 ArenaXBrokerAPI_v2.get_snapshots 的實作，
    # 它內部也只是 for product in products 逐一打 middleware.snapshot()，並沒有真的
    # batch endpoint——包成一次呼叫並不會少打幾次 API，所以維持這個最簡單的寫法。
    # 如果之後換了真的支援批次查詢的 broker，這裡再依實際情況調整。
    async def _reload_loop(self):
        interval = 60 / self.playback_speed
        while True:
            for symbol in list(self.watch_list):
                try:
                    # _snapshot() calls out to a real broker in real mode —
                    # blocking network I/O — so keep it off the event loop even
                    # though the mock path doesn't strictly need to be there.
                    tick = await asyncio.to_thread(self._snapshot, symbol)
                except Exception as e:
                    # A single broker hiccup shouldn't take the whole feed down —
                    # log it and try the next symbol/cycle.
                    log.warning(f"[Master] Snapshot fetch failed for {symbol}: {e}")
                    continue
                await self._broadcast(tick)
            await asyncio.sleep(interval)

    def subscribe_price_feed(self, symbol: str):
        self.watch_list.add(symbol)

    def start(self, pub_socket):
        self.pub_socket = pub_socket
        return asyncio.create_task(self._reload_loop())


### 下單執行權收回 master：bot 不再自己撮合/記帳，只送「我想下單」的 intent
### 過來；真正改變 balance/position 的地方只有這裡一處。account_client=None 時
### 退回 paper-mode ledger（每個 bot 各自一份，key by bot_id），future 接上真實
### broker 後 `_execute_via_broker` 才會是唯一被呼叫的路徑 —— 兩條路徑都回傳
### 同一種 dict 格式，呼叫端 (main.py 的 order loop) 不用管現在走的是哪一條。
class ExecutionEngine:
    def __init__(self, account_client: AccountClient | None):
        self.client = account_client
        self._ledger: dict[str, dict] = {}  # bot_id -> {"balance": float, "positions": {symbol: {...}}}

    def _account_for(self, bot_id: str) -> dict:
        return self._ledger.setdefault(bot_id, {"balance": INITIAL_BALANCE, "positions": {}})

    async def execute(self, order: dict) -> dict:
        if self.client is not None:
            # AccountClient's broker calls are blocking network I/O — must not
            # run them directly on the asyncio loop, or every bot's order would
            # stall price-feed broadcasting until the broker responds.
            return await asyncio.to_thread(self._execute_via_broker, order)
        return self._execute_paper(order)

    # No risk management / risk guard for now for simplicity
    def _execute_via_broker(self, order: dict) -> dict:
        symbol, action, qty, price = order["symbol"], order["action"], order["qty"], order["price"]

        try:
            if action == "BUY":
                result = self.client.buy_stock(symbol=symbol, quantity=qty, price=price, intraday_odd=True)
            elif action == "SELL":
                result = self.client.sell_stock(symbol=symbol, quantity=qty, price=price, intraday_odd=True)
            else:
                return self._reply_from_broker(order, status="REJECTED", filled_qty=0,
                                                 reason=f"unknown action {action}")
        except Exception as e:
            return self._reply_from_broker(order, status="REJECTED", filled_qty=0, reason=str(e))

        # Only FILLED counts as done for this PoC — PLACED/COMMITTED_*/PARTIAL
        # would need resting-order tracking over time, which we don't have yet.
        if result.status != OrderStatus.FILLED:
            return self._reply_from_broker(order, status="REJECTED", filled_qty=0,
                                            reason=f"{result.status}: {result.message}")

        return self._reply_from_broker(order, status="FILLED", filled_qty=qty, reason=order.get("reason", ""))

    def _reply_from_broker(self, order: dict, status: str, filled_qty: int, reason: str) -> dict:
        # Ask the broker for the authoritative post-trade state rather than
        # computing it ourselves — same contract as _reply()/_execute_paper,
        # just backed by a real sync instead of an in-memory ledger.
        symbol = order["symbol"]
        balance = self.client.get_balance()
        positions = self.client.get_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
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
                return self._reply(order, acct, status="REJECTED", filled_qty=0,
                                    reason="insufficient balance" if qty > 0 else "invalid qty")
            acct["balance"] -= price * qty
            pos = acct["positions"].setdefault(symbol, {"quantity": 0, "avg_cost": 0.0})
            total_shares = pos["quantity"] + qty
            pos["avg_cost"] = (pos["quantity"] * pos["avg_cost"] + qty * price) / total_shares
            pos["quantity"] = total_shares

        elif action == "SELL":
            pos = acct["positions"].get(symbol)
            if not pos or pos["quantity"] < qty or qty <= 0:
                return self._reply(order, acct, status="REJECTED", filled_qty=0, reason="no/insufficient position")
            acct["balance"] += price * qty
            pos["quantity"] -= qty
            if pos["quantity"] == 0:
                pos["avg_cost"] = 0.0

        else:
            return self._reply(order, acct, status="REJECTED", filled_qty=0, reason=f"unknown action {action}")

        return self._reply(order, acct, status="FILLED", filled_qty=qty, reason=order.get("reason", ""))

    def _reply(self, order: dict, acct: dict, status: str, filled_qty: int, reason: str) -> dict:
        symbol = order["symbol"]
        return {
            "b_id": order["b_id"], "status": status, "action": order.get("action"),
            "symbol": symbol, "qty": filled_qty, "price": order.get("price"), "t": time.time(),
            "balance": acct["balance"],
            "position": dict(acct["positions"].get(symbol, {"quantity": 0, "avg_cost": 0.0})),
            "reason": reason,
        }


# 使用 zmq 的 asyncio 版本的 Context
ctx = zmq.asyncio.Context()

async def handle_orders(pull_socket, pub_socket, engine: ExecutionEngine):
    """Fan-in: every bot's order intent lands here, gets executed by the single
    ExecutionEngine, and the resulting Fill/Rejection is published back to that
    bot alone (PUB topic = bot_id) so its local state mirror stays in sync.
    """
    log.info("[Master] Started order execution loop...")
    while True:
        try:
            msg = await pull_socket.recv()
            order = msgpack.unpackb(msg)
            fill = await engine.execute(order)
            log.info(f"[Master] {fill['status']} {fill['action']} {fill['symbol']} x{fill['qty']} "
                      f"@ {fill['price']} for {fill['b_id']} ({fill['reason']})")
            await pub_socket.send_multipart([fill["b_id"].encode('utf-8'), msgpack.packb(fill)])
        except Exception as e:
            log.info(f"[Master] Got exception while handling order: {e}")

async def main():
    #####################  INTERNAL STUB FUNCTION  ######################
    def get_enabled_bots():
        return ["Bot_A", "Bot_B", "Bot_C"]
    #####################  INTERNAL STUB FUNCTION  ######################

    # Socket 1 for publishing price feed
    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind(CJ_ENGINE_SOCKET_SUB_PRICE)

    # Socket 2 for receiving info from bots
    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind(CJ_ENGINE_SOCKET_PUSH_STATE)

    # Connect to the broker FIRST and fail fast — no point spawning bot
    # subprocesses (and waiting 2s for them) if there's nothing to feed them.
    # ArenaX only needs this one hardcoded key, nothing else.
    account_client = AccountClient(broker_type=BrokerType.ARENAX, arenax_port=8802, api_key="testkey123")
    if not await asyncio.to_thread(account_client.connect):
        log.error("[Master] Failed to connect to ArenaX broker (port 8802) — aborting.")
        return

    # Iterate all enabled bot definitions
    bots = get_enabled_bots()
    processes = []
    # proc_a = await asyncio.create_subprocess_exec(sys.executable, '-u', str(BOT_A_SCRIPT), bots[0])
    # proc_b = await asyncio.create_subprocess_exec(sys.executable, '-u', str(BOT_B_SCRIPT), bots[1])
    proc_c = await asyncio.create_subprocess_exec(sys.executable, '-u', str(BOT_C_SCRIPT), bots[2])
    # processes.append(proc_a)
    # processes.append(proc_b)
    processes.append(proc_c)

    await asyncio.sleep(2) # 等待子進程 ZMQ 連線建立完成

    # Same account_client instance shared by EventHub (讀行情) and
    # ExecutionEngine（寫下單）— one broker session, not two.
    hub = EventHub(account_client=account_client, playback_speed=60.0)

    # This two API should provide to client-side application
    hub.subscribe_price_feed("0050")
    hub.subscribe_price_feed("2357")
    hub.subscribe_price_feed("2317")
    hub.subscribe_price_feed("00919")

    # Execution engine: the only place that actually executes/records trades.
    engine = ExecutionEngine(account_client=account_client)
    asyncio.create_task(handle_orders(pull_socket, pub_socket, engine))

    try:
        reload_task = hub.start(pub_socket)
        await reload_task

    finally:
        # Clean up
        log.info("\n[Master] Terminating all bots...")
        for proc in processes:
            try:
                proc.terminate()
                await proc.wait()
            except:
                pass
        log.info("[Master] Trading engine terminated.")
        account_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
