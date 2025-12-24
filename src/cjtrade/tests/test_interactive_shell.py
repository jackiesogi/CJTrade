# Interactive shell
# Supported commands:
#   help:   Show this help message
#   lsodr:  List all orders
#   lspos:  List all positions
#   exit:   Close interactive shell
import pandas as pd
from cjtrade.core.account_client import AccountClient
from cjtrade.tests.test_basic_flow import *

exit_flag = False


def set_exit_flag(client: AccountClient):
    global exit_flag
    exit_flag = True



def test_sinopac_buy_0050(client: AccountClient):
    order_result = client.buy_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")

def test_sinopac_sell_0050(client: AccountClient):
    order_result = client.sell_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")

def test_sinopac_bidask_0050(client: AccountClient):
    product = Product(
        type=ProductType.STOCK,
        exchange=Exchange.TSE,
        symbol="0050"
    )
    bid_ask = client.get_bid_ask(product, intraday_odd=True)
    print(f"Bid/Ask for 0050: {bid_ask}")

def test_sinopac_get_account_positions(client: AccountClient):
    positions = client.get_positions()

    df = pd.DataFrame([p.__dict__ for p in positions])
    print(df)


def test_sinopac_get_account_balance(client: AccountClient):
    balance = client.get_balance()
    print(f"Account Balance: {balance}")


def test_sinopac_cancel_all_orders(client: AccountClient):
    try:
        api = client.broker.api
        api.update_status()
        trades = api.list_trades()

        print(f"{len(trades)} entries found.")

        cancelled_count = 0
        for i, trade in enumerate(trades):
            try:
                # Only cancel orders that are not yet filled
                status = trade.status.status.value
                print(f"\nProcessing {i+1}/{len(trades)}")
                print(f"  ID: {trade.status.id}")
                print(f"  Product: {getattr(trade.contract, 'code', 'N/A')}")
                print(f"  Status: {status}")
                print(f"  Quantity: {trade.order.quantity}")
                print(f"  Price: {trade.order.price}")

                # Only cancel orders that are not yet filled
                if status in ['PreSubmitted', 'Submitted', 'PartialFilled']:
                    print(f"  → Trying to cancel...")
                    result = api.cancel_order(trade)
                    print(f"  → Cancel result: {result}")
                    cancelled_count += 1
                else:
                    print(f"  → Skipping (Status: {status})")

            except Exception as e:
                print(f"  → Cancel failed: {e}")

        print(f"\n=== Processing complete ===")
        print(f"Attempted to cancel {cancelled_count} orders")

        # Check cancellation results
        print("\n=== Check cancellation results ===")
        api.update_status()
        remaining_trades = api.list_trades()
        active_orders = [t for t in remaining_trades if t.status.status.value in ['PreSubmitted', 'Submitted', 'PartialFilled']]
        print(f"Remaining active orders: {len(active_orders)}")

        if active_orders:
            print("Still have active orders:")
            for trade in active_orders:
                print(f"  ID: {trade.status.id}, Status: {trade.status.status.value}")
        else:
            print("All orders have been successfully canceled or completed")

    except Exception as e:
        print(f"Error occurred while canceling orders: {e}")


def test_sinopac_list_orders_real(client: AccountClient):
    print("=== Test Order List Query ===")

    try:
        orders = client.list_orders()
        print(f"Found {len(orders)} orders")

        if orders:
            print("\nRecent 5 orders:")
            for i, order in enumerate(orders[-5:]):
                print(f"\nOrder {i+1}:")
                print(f"  Order ID: {order.get('id', 'N/A')}")
                print(f"  Symbol: {order.get('symbol', 'N/A')}")
                print(f"  Action: {order.get('action', 'N/A')}")
                print(f"  Quantity: {order.get('quantity', 'N/A')}")
                print(f"  Price: {order.get('price', 'N/A')}")
                print(f"  Status: {order.get('status', 'N/A')}")
                print(f"  Order Type: {order.get('order_type', 'N/A')}")
                print(f"  Price Type: {order.get('price_type', 'N/A')}")
                print(f"  Order Lot: {order.get('order_lot', 'N/A')}")
                print(f"  Order Time: {order.get('order_datetime', 'N/A')}")
                print(f"  Deals: {order.get('deals', 'N/A')}")
                print(f"  Order Number: {order.get('ordno', 'N/A')}")
        else:
            print("No orders found")

    except Exception as e:
        print(f"Error occurred while querying orders: {e}")


def show_help(client: AccountClient):
    print("help:    Show this help message")
    print("clear:   Clear the screen")
    print("lsodr:   List all orders")
    print("lspos:   List all positions")
    print("buy:     Place a buy order for 0050")
    print("sell:    Place a sell order for 0050")
    print("snap:    Get market snapshot for 0050")
    print("bidask:  Get bid/ask for 0050")
    print("cancel:  Cancel all active orders")
    print("balance: Show account balance")
    print("exit:    Close interactive shell")


def clear_screen(client: AccountClient):
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


def test_sinopac_get_snapshot_0050(client: AccountClient):
    product = Product(symbol="0050")
    snapshots = client.get_snapshot([product])
    df = pd.DataFrame([s.__dict__ for s in snapshots])
    print(df)

command_func_map = {
    "help": show_help,
    "lsodr": test_sinopac_list_orders_real,
    "lspos": test_sinopac_get_account_positions,
    "buy": test_sinopac_buy_0050,
    "sell": test_sinopac_sell_0050,
    "bidask": test_sinopac_bidask_0050,
    "snap": test_sinopac_get_snapshot_0050,
    "cancel": test_sinopac_cancel_all_orders,
    "balance": test_sinopac_get_account_balance,
    "clear": clear_screen,
    "exit": set_exit_flag,
}


def process_command(cmd: str, client: AccountClient):
    cmd = cmd.strip()

    if not cmd:
        return

    func = command_func_map.get(cmd)
    if func is None:
        print(f"Unknown command: {cmd}")
        print("Type 'help' to see available commands")
        return

    try:
        func(client)
    except Exception as e:
        print(f"Command failed: {e}")


# def interactive_shell(client: AccountClient):
#     global exit_flag
#     exit_flag = False

#     print("Interactive shell started. Type 'help' for commands.")

#     while not exit_flag:
#         cmd = input("> ")
#         process_command(cmd, client)

#     print("Bye!")

import readline
MAX_HISTORY_SIZE = 30

def init_readline():
    readline.set_history_length(MAX_HISTORY_SIZE)
    readline.parse_and_bind("tab: complete")

def interactive_shell(client: AccountClient):
    global exit_flag
    exit_flag = False

    init_readline()
    print("Interactive shell started. Type 'help' for commands.")
    while not exit_flag:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            readline.add_history(cmd)
            process_command(cmd, client)

        except (EOFError, KeyboardInterrupt):
            break
    print("Bye!")


if __name__ == "__main__":
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    interactive_shell(client)
    client.disconnect()
