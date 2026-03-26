import os

from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from cjtrade.pkgs.db.db_api import *
from cjtrade.pkgs.models import *

symbols = ['0050', '2330', '2317']
load_supported_config_files()

config = {
    "api_key": os.getenv("API_KEY"),
    "secret_key": os.getenv("SECRET_KEY"),
    "ca_path": os.getenv("CA_CERT_PATH"),
    "ca_passwd": os.getenv("CA_PASSWORD")
}


def download_price(account, conn):
    for symbol in symbols:
        print(f"Fetched price for {symbol}:")
        prices = account.get_kbars(Product(symbol=symbol), start="2024-01-01", end="2024-06-30", interval="1m")
        for price in prices:
            insert_price_to_arenax_local_price_db(conn=conn,
                                                  symbol=symbol,
                                                  price=price,
                                                  timeframe="1m",
                                                  source="sinopac",
                                                  overwrite=True)
        print(f"Wrote {len(prices)} price entries for {symbol} to local database.")



def main():
    a = AccountClient(broker_type=BrokerType.SINOPAC, **config)
    a.connect()
    c = connect_sqlite(database="arenax_price.db")
    prepare_arenax_local_price_db_tables(conn=c)
    download_price(a, c)
    c.close()
    a.disconnect()

if __name__ == "__main__":
    main()
