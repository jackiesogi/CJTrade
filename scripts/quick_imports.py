import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cjtrade.models.kbar import Kbar
from cjtrade.models.order import *
from cjtrade.models.product import *
from cjtrade.models.position import Position
from cjtrade.models.quote import *
from cjtrade.core.account_client import AccountClient, BrokerType
from cjtrade.brokers.sinopac.sinopac_broker_api import SinopacBrokerAPI
from cjtrade.brokers.mock.mock_broker_api import MockBrokerAPI
from cjtrade.chart.kbar_client import KbarChartClient, KbarChartType
# from cjtrade.analytics.technical.indicators.sma import SimpleMovingAverage as SMA
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

def get_config():
    return {
        'api_key': os.getenv('API_KEY'),
        'secret_key': os.getenv('SECRET_KEY'),
        'ca_path': os.getenv('CA_CERT_PATH'),
        'ca_passwd': os.getenv('CA_PASSWORD'),
        'simulation': False
    }

def get_client(broker_type=BrokerType.SINOPAC):
    client = AccountClient(broker_type, **get_config())
    client.connect()
    return client

""" Example usage:
#!/usr/bin/env python3
from cjtrade.scripts.quick_imports import *

client = get_client()
kbars = client.get_kbars(Product(symbol="2330"), start='2025-01-15', end='2025-01-15', interval="1m")
print(f"Got {len(kbars)} kbars")
client.disconnect()
"""