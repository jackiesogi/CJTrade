import logging
import sys

import msgpack
import zmq

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("poc.bot_b")

# Config
CJ_ENGINE_SOCKET_SUB_PRICE = "tcp://127.0.0.1:5555"
CJ_ENGINE_SOCKET_PUSH_STATE = "tcp://127.0.0.1:5556"

def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    target_symbol = "2357"
    log.info(f"[{bot_id}] started! ({target_symbol})")

    context = zmq.Context()

    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(CJ_ENGINE_SOCKET_SUB_PRICE)
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))

    push_socket = context.socket(zmq.PUSH)
    push_socket.connect(CJ_ENGINE_SOCKET_PUSH_STATE)

    try:
        while True:
            topic, payload = sub_socket.recv_multipart()
            data = msgpack.unpackb(payload)

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
