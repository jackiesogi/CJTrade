import asyncio
import random
import sys
import time
from pathlib import Path

import msgpack
import zmq.asyncio
from cjtrade.pkgs.brokers.account_client import AccountClient

BOT_SCRIPT = Path(__file__).resolve().parent / "bot.py"
# BOT_SCRIPT = Path(__file__).resolve().parent / "bot.py"

###
###
###
class EventHub:
    def __init__(self, account_client: AccountClient, playback_speed: float):
        self.client = account_client
        self.playback_speed = playback_speed
        # self.playback_speed = 120.0
        self.watch_list = set()
        self.pub_socket = None

    async def _broadcast(self, tick: dict):
        symbol = tick["s"]
        payload = msgpack.packb(tick)
        # Send multipart: [Topic, Data]，same with bot.py per-symbol topic filtering.
        await self.pub_socket.send_multipart([symbol.encode('utf-8'), payload])
        print(f"[Master] Broadcasting {symbol} at {tick['p']}...")

    # Stub snapshot function
    # TODO: Connect with broker -> self.client.get_snapshots([Product(symbol=s) for s in ...])
    # get_snapshots 本身吃 List[Product] 一次打包查詢，屆時可以在 _reload_loop 每輪只呼叫一次
    # Batch get watch_list latest price, and broadcast separately.
    def _snapshot(self, symbol: str) -> dict:
        return {"s": symbol, "p": round(random.uniform(90, 110), 2), "t": time.time()}

    # we will trigger _reload_loop every 1 / playback_speed second
    # and in each reload loop, broadcast the kbar price feed.
    # the bot themselves will filter their data of interest.
    #
    # 這裡選擇「一次 snapshot 就一次 broadcast」：watch_list 內每個 symbol 各自
    # snapshot 完立刻送出，而不是全部 symbol 湊成一包再一次送出。原因是 bot.py
    # 訂閱端是用 ZMQ topic (symbol) 做過濾，PUB/SUB 本來就是一則訊息對一個 topic，
    # 沒有「一包多 symbol」的合併訊息格式；真的要批次的話，能批次的地方是
    # snapshot 的「查詢」（一次呼叫 get_snapshots 拿多個 symbol），而不是 broadcast
    # 本身。如果你想要的是別的批次方式（例如把整個 watch_list 包成一則訊息，
    # 由 bot 端自己拆包過濾），跟我說一聲，這裡可以再調整。
    async def _reload_loop(self):
        interval = 1 / self.playback_speed
        while True:
            for symbol in list(self.watch_list):
                tick = self._snapshot(symbol)
                await self._broadcast(tick)
            await asyncio.sleep(interval)

    def subscribe_price_feed(self, symbol: str):
        self.watch_list.add(symbol)

    def start(self, pub_socket):
        self.pub_socket = pub_socket
        return asyncio.create_task(self._reload_loop())


# 使用 zmq 的 asyncio 版本的 Context
ctx = zmq.asyncio.Context()

async def receive_reports(pull_socket):
    """Independent non-blocking task for receiving fill/error reports in real time"""
    print("[Master] Started monitoring process...")
    while True:
        try:
            msg = await pull_socket.recv()
            report = msgpack.unpackb(msg)
            print(f"[Master] Got signal from bot {report['b_id']} | Action: {report['type']} | Price: {report['p']}")
        except Exception as e:
            print(f"[Master] Got exception: {e}")

async def main():
    #####################  INTERNAL STUB FUNCTION  ######################
    def get_enabled_bots():
        return ["Bot_A", "Bot_B"]
    #####################  INTERNAL STUB FUNCTION  ######################

    # Socket 1 for publishing price feed
    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind("tcp://127.0.0.1:5555")

    # Socket 2 for receiving info from bots
    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind("tcp://127.0.0.1:5556")

    # Iterate all enabled bot definitions
    bots = get_enabled_bots()
    processes = []
    for b_id in bots:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(BOT_SCRIPT), b_id
        )
        processes.append(proc)

    await asyncio.sleep(2) # 等待子進程 ZMQ 連線建立完成

    # Launch task for receiving info from bots
    asyncio.create_task(receive_reports(pull_socket))

    # Event hub (NEW!!!)
    # account_client=None：還沒接上真實/ArenaX broker，_snapshot 先用亂數模擬價格
    hub = EventHub(account_client=None, playback_speed=2.0)
    hub.subscribe_price_feed("BTCUSDT")
    hub.subscribe_price_feed("ETHUSDT")  # Bot_A / Bot_B 只認 BTCUSDT，會自動忽略這條

    try:
        reload_task = hub.start(pub_socket)
        await reload_task

    finally:
        # Clean up
        print("\n[Master] Terminating all bots...")
        for proc in processes:
            try:
                proc.terminate()
                await proc.wait()
            except:
                pass
        print("[Master] Trading engine terminated.")


if __name__ == "__main__":
    asyncio.run(main())
