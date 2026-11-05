import logging
import sys

import msgpack
import zmq

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.bot_a")

# Config
CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    # 假設這個機器人只關心 0050
    target_symbol = "0050"
    log.info(f"[{bot_id}] started! ({target_symbol})")

    context = zmq.Context()

    # 1. 訂閱行情 - 精準訂閱特定商品 (Topic)
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(CJ_ENGINE_SOCKET_SUB_PRICE)
    # 關鍵：只接收開頭為商品名稱的字節流
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))

    # 2. 回報狀態
    push_socket = context.socket(zmq.PUSH)
    push_socket.connect(CJ_ENGINE_SOCKET_PUSH_STATE)

    try:
        while True:
            # ZeroMQ 會自動幫我們過濾，這裡收到的絕對只有 BTCUSDT 的資料
            topic, payload = sub_socket.recv_multipart()
            data = msgpack.unpackb(payload) # 極速解包

            # --- Tick / K線 策略邏輯 ---
            price = data["p"] # 建議欄位名稱縮寫 (p=price, v=volume) 減少 Tick 帶寬

            if price > 105.0:
                # Order intent, not an already-executed report — master's
                # ExecutionEngine is the one that actually fills/records it.
                order = {"b_id": bot_id, "action": "BUY", "symbol": target_symbol,
                         "qty": 1, "price": price, "reason": "price>105", "t": data["t"]}
                push_socket.send(msgpack.packb(order))

    except KeyboardInterrupt:
        log.info(f"[{bot_id}] exited without error")

if __name__ == "__main__":
    main()
