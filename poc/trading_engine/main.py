import asyncio
import sys
import time
from pathlib import Path

import msgpack
import zmq.asyncio

BOT_SCRIPT = Path(__file__).resolve().parent / "bot.py"

### PoC_1: Bot_{1..10} 可以在指定的時間被發佈到 engine 並印出 "Bot started!"
###
###

# 使用 zmq 的 asyncio 版本的 Context
ctx = zmq.asyncio.Context()

async def receive_reports(pull_socket):
    """獨立的非阻塞協程：專職、即時接收所有機器人的成交/錯誤回報"""
    print("[Master] Started monitoring process...")
    while True:
        try:
            msg = await pull_socket.recv()
            report = msgpack.unpackb(msg)
            print(f"[Master] Got signal from bot {report['b_id']} | Action: {report['type']} | Price: {report['p']}")
        except Exception as e:
            print(f"[Master] Got exception: {e}")

async def main():
    # 1. 初始化 Socket
    pub_socket = ctx.socket(zmq.PUB)
    pub_socket.bind("tcp://127.0.0.1:5555")

    pull_socket = ctx.socket(zmq.PULL)
    pull_socket.bind("tcp://127.0.0.1:5556")

    # 2. 動態佈署子進程 (Subprocess)
    bots = ["Bot_A", "Bot_B"]
    processes = []
    for b_id in bots:
        # 使用不卡住主線程的方式啟動子進程
        proc = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(BOT_SCRIPT), b_id
        )
        processes.append(proc)

    await asyncio.sleep(2) # 等待子進程 ZMQ 連線建立完成

    # 3. 啟動背景回報監聽工作 (不會卡住行情發送)
    asyncio.create_task(receive_reports(pull_socket))

    # print("[Master] 開始發送行情資料...")

    # 模擬高頻 Tick/K線 數據流
    mock_ticks = [
        {"s": "BTCUSDT", "p": 101.2, "t": time.time()},
        {"s": "ETHUSDT", "p": 3200.5, "t": time.time()}, # Bot_A 會自動忽略這條
        {"s": "BTCUSDT", "p": 102.2, "t": time.time()},
        {"s": "BTCUSDT", "p": 104.2, "t": time.time()},
        {"s": "BTCUSDT", "p": 105.8, "t": time.time()}, # 觸發 Bot_A 買入
        {"s": "BTCUSDT", "p": 104.2, "t": time.time()},
        {"s": "BTCUSDT", "p": 105.2, "t": time.time()},
        {"s": "BTCUSDT", "p": 106.2, "t": time.time()},
        {"s": "ETHUSDT", "p": 3200.5, "t": time.time()}, # Bot_A 會自動忽略這條
        {"s": "BTCUSDT", "p": 103.2, "t": time.time()},
    ]

    try:
        for tick in mock_ticks:
            symbol = tick["s"]
            # 使用 msgpack 打包
            payload = msgpack.packb(tick)

            # 發送 multipart: [Topic, Data]
            # ZMQ 底層會根據第一個 element (Topic) 做高效路由過濾
            await pub_socket.send_multipart([symbol.encode('utf-8'), payload])
            print(f"[Master] Broadcasting {symbol} at {tick['p']}...")

            # 模擬 Tick 之間的時間間隔 (K線級可調大，Tick級可降到 0.001 秒或更低)
            await asyncio.sleep(0.5)

    finally:
        # 4. 關閉清理
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
