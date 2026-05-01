import time

from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.models.product import ProductType

client = ArenaXBrokerAPI_v2(api_key='testkey123')
res = client.connect()
print(f"client connect status: {res}")
pos = client.get_positions()
print(pos)
ts  = client.get_market_time()
print(ts)

try:
    kbars = client.get_kbars(product=Product('0050'), start='2024-01-01', end='2025-01-01', interval='1m')
    print(len(kbars))
    kbars = client.get_kbars(product=Product('0050'), start='2024-01-01', end='2025-01-01', interval='5m')
    print(len(kbars))
    kbars = client.get_kbars(product=Product('0050'), start='2024-01-01', end='2025-01-01', interval='1h')
    print(len(kbars))
    kbars = client.get_kbars(product=Product('0050'), start='2024-01-01', end='2025-01-01', interval='1d')
    print(len(kbars))
except Exception as e:
    print(f"Error fetching kbars: {e}")

kbars = client.get_kbars(product=Product('2330'), start='2000-01-01', end='2004-01-01', interval='1d')
print(len(kbars))
print(kbars[0])

time.sleep(3)
res = client.disconnect()
print(f"client disconnect status: {res}")
