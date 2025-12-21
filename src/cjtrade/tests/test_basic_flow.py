"""
Simple test for AccountClient with Sinopac broker
Test flow: login() -> get_positions() -> logout()
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from cjtrade.core.account_client import *


load_dotenv()

config = {
    'api_key': os.environ["API_KEY"],
    'secret_key': os.environ["SECRET_KEY"],
    'ca_path': os.environ["CA_CERT_PATH"],
    'ca_passwd': os.environ["CA_PASSWORD"],
    'simulation': True  # Use production environment to see actual holdings
}

def test_sinopac_basic_flow_simple():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    positions = client.get_positions()
    for pos in positions:
        print(f"{pos.symbol}: {pos.quantity} @ {pos.avg_cost}, PnL: {pos.unrealized_pnl}")
    client.disconnect()

def test_sinopac_buy_0050():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    order_result = client.buy_stock("0050", quantity=1, price=62.6, intraday_odd=True)
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
    pass
    # client = AccountClient(BrokerType.SINOPAC, **config)
    # client.connect()
    # positions = client.get_positions()
    # for pos in positions:
    #     print(f"{pos.symbol}: {pos.quantity} @ {pos.avg_cost}, PnL: {pos.unrealized_pnl}")
    # client.disconnect()

def test_sinopac_get_account_balance():
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    balance = client.get_balance()
    print(f"Account Balance: {balance}")
    client.disconnect()

def test_sinopac_buy_0050_intraday_odd():
    pass


if __name__ == "__main__":
    # test_sinopac_bidask_0050()
    # test_sinopac_basic_flow_simple()
    # test_sinopac_get_account_positions()
    test_sinopac_buy_0050()
    test_sinopac_get_account_balance()