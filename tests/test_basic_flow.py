"""
Simple test for AccountClient with Sinopac broker
Test flow: login() -> get_positions() -> logout()
"""
import os
import sys
from pathlib import Path

from cjtrade.core.account_client import *
from dotenv import load_dotenv


load_dotenv()

config = {
    'api_key': os.environ["API_KEY"],
    'secret_key': os.environ["SECRET_KEY"],
    'ca_path': os.environ["CA_CERT_PATH"],
    'ca_passwd': os.environ["CA_PASSWORD"],
    'simulation': False  # Use production environment to see actual holdings
}

def test_sinopac_buy_0050():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    order_result = client.buy_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")
    # commit_result = client.commit_order(order_result.linked_order)
    # print(f"--- commit_result: {commit_result}")
    client.disconnect()

def test_sinopac_sell_0050():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    order_result = client.sell_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")
    client.disconnect()

def test_sinopac_bidask_0050():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    product = Product(
        type=ProductType.STOCK,
        exchange=Exchange.TSE,
        symbol="0050"
    )
    bid_ask = client.get_bid_ask(product, intraday_odd=True)
    print(f"Bid/Ask for 0050: {bid_ask}")
    client.disconnect()

def test_sinopac_get_account_positions():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    positions = client.get_positions()
    print(f"{'Symbol':^10} {'Quantity':^8} {'Avg Cost':^10} {'Unrealized PnL':^15}")
    print("-" * 46)

    for pos in positions:
        print(
            f"{pos.symbol:^10} "
            f"{pos.quantity:^8} "
            f"{pos.avg_cost:>10.2f} "
            f"{pos.unrealized_pnl:>15.2f}"
        )
    client.disconnect()

def test_sinopac_get_account_balance():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    balance = client.get_balance()
    print(f"Account Balance: {balance}")
    client.disconnect()

def test_sinopac_buy_0050_intraday_odd_real():
    real_config = {
            'api_key': os.environ["API_KEY"],
            'secret_key': os.environ["SECRET_KEY"],
            'ca_path': os.environ["CA_CERT_PATH"],
            'ca_passwd': os.environ["CA_PASSWORD"],
            'simulation': False
    }
    client = AccountClient(BrokerType.SINOPAC, **real_config)
    client.connect()

    order_result = client.buy_stock("0050", quantity=5, price=62.6, intraday_odd=True)
    print(f"Order Result: ID={order_result.id}, Status={order_result.status}, Message={order_result.message}")

    print("Committing order...")
    commit_result = client.commit_order()
    print(f"Commit Result: ID={commit_result.id}, Status={commit_result.status}, Message={commit_result.message}")

    client.disconnect()


def test_sinopac_cancel_all_orders():
    """Cancel all pending orders in real environment"""
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()

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
                if status in ['PreSubmitted', 'Submitted', 'PartFilled']:
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
        active_orders = [t for t in remaining_trades if t.status.status.value in ['PreSubmitted', 'Submitted', 'PartFilled']]
        print(f"Remaining active orders: {len(active_orders)}")

        if active_orders:
            print("Still have active orders:")
            for trade in active_orders:
                print(f"  ID: {trade.status.id}, Status: {trade.status.status.value}")
        else:
            print("All orders have been successfully canceled or completed")

    except Exception as e:
        print(f"Error occurred while canceling orders: {e}")

    client.disconnect()


def test_sinopac_list_orders_real():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()

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

    client.disconnect()


def enter_interactive_shell():
    pass


if __name__ == "__main__":
    # test_sinopac_bidask_0050()

    # test_sinopac_get_account_positions()

    # test_sinopac_buy_0050()

    test_sinopac_get_account_balance()
    # test_sinopac_buy_0050_intraday_odd_real()
    # test_sinopac_api_methods()
    # test_sinopac_list_orders_real()
    # test_sinopac_cancel_all_orders()  # 緊急取消所有委託單
