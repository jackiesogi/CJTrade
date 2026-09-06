import sys

import msgpack
import zmq

def main():
    bot_id = sys.argv[1] if len(sys.argv) > 1 else "Bot_Generic"
    # 假設這個機器人只關心 BTCUSDT
    target_symbol = "BTCUSDT"
    print(f"[{bot_id}] started! ({target_symbol})")

    context = zmq.Context()

    # 1. 訂閱行情 - 精準訂閱特定商品 (Topic)
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect("tcp://127.0.0.1:5555")
    # 關鍵：只接收開頭為商品名稱的字節流
    sub_socket.set(zmq.SUBSCRIBE, target_symbol.encode('utf-8'))

    # 2. 回報狀態
    push_socket = context.socket(zmq.PUSH)
    push_socket.connect("tcp://127.0.0.1:5556")

    try:
        while True:
            # ZeroMQ 會自動幫我們過濾，這裡收到的絕對只有 BTCUSDT 的資料
            topic, payload = sub_socket.recv_multipart()
            data = msgpack.unpackb(payload) # 極速解包

            # --- Tick / K線 策略邏輯 ---
            price = data["p"] # 建議欄位名稱縮寫 (p=price, v=volume) 減少 Tick 帶寬

            if price > 105.0:
                report = {"b_id": bot_id, "type": "BUY", "p": price, "t": data["t"]}
                push_socket.send(msgpack.packb(report))

    except KeyboardInterrupt:
        print(f"[{bot_id}] exited without error")

if __name__ == "__main__":
    main()
