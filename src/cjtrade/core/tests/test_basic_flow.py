"""
Simple test for AccountClient with Sinopac broker
Test flow: login() -> get_positions() -> logout()
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from cjtrade.core.account_client import AccountClient, BrokerType


load_dotenv()

def test_sinopac_basic_flow_simple():
    config = {
        'api_key': os.environ["API_KEY"],
        'secret_key': os.environ["SECRET_KEY"],
        'ca_path': os.environ["CA_CERT_PATH"],
        'ca_passwd': os.environ["CA_PASSWORD"],
        'simulation': False  # Use production environment to see actual holdings
    }
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    positions = client.get_positions()
    for pos in positions:
        print(f"{pos.symbol}: {pos.quantity} @ {pos.avg_cost}, PnL: {pos.unrealized_pnl}")
    client.disconnect()


if __name__ == "__main__":
    test_sinopac_basic_flow_simple()