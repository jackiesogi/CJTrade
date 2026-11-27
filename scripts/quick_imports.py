import os
from datetime import datetime
from datetime import timedelta

from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
from cjtrade.pkgs.chart.kbar_client import KbarChartClient
from cjtrade.pkgs.chart.kbar_client import KbarChartType
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import *
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.product import *
from cjtrade.pkgs.models.quote import *
from dotenv import load_dotenv
# from cjtrade.pkgs.analytics.technical.indicators.sma import SimpleMovingAverage as SMA

load_dotenv()

def get_config():
    return {
        'api_key': os.getenv('API_KEY'),
        'secret_key': os.getenv('SECRET_KEY'),
        'ca_path': os.getenv('CA_CERT_PATH'),
        'ca_passwd': os.getenv('CA_PASSWORD'),
        'simulation': os.getenv('SIMULATION', 'y') == 'y',   # sandbox unless SIMULATION=n
    }

def get_client(broker_type=BrokerType.SINOPAC):
    client = AccountClient(broker_type, **get_config())
    client.connect()
    return client

""" Example usage:
#!/usr/bin/env python3
exec(open('scripts/quick_imports.py').read())   # from the repo root

client = get_client()
kbars = client.get_kbars(Product(symbol="2330"), start='2025-01-15', end='2025-01-15', interval="1m")
print(f"Got {len(kbars)} kbars")
client.disconnect()
"""
