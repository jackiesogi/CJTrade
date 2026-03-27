##   ____       _            ____                      _                 _
##  |  _ \ _ __(_) ___ ___  |  _ \  _____      ___ __ | | ___   __ _  __| | ___ _ __
##  | |_) | '__| |/ __/ _ \ | | | |/ _ \ \ /\ / / '_ \| |/ _ \ / _` |/ _` |/ _ \ '__|
##  |  __/| |  | | (_|  __/ | |_| | (_) \ V  V /| | | | | (_) | (_| | (_| |  __/ |
##  |_|   |_|  |_|\___\___| |____/ \___/ \_/\_/ |_| |_|_|\___/ \__,_|\__,_|\___|_|
import argparse
import os

from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from cjtrade.pkgs.db.db_api import *
from cjtrade.pkgs.models import *


def download_price(account, conn, symbols, start, end):
    for symbol in symbols:
        print(f"Fetched price for {symbol}:")
        prices = account.get_kbars(Product(symbol=symbol), start=start, end=end, interval="1m")
        for price in prices:
            insert_price_to_arenax_local_price_db(conn=conn,
                                                  symbol=symbol,
                                                  price=price,
                                                  timeframe="1m",
                                                  source="sinopac",
                                                  overwrite=True)
        print(f"Wrote {len(prices)} price entries for {symbol} to local database.")

import os
import argparse

def parse_args():
    env_symbols = [s for s in os.getenv("WATCH_LIST", "").split(",") if s]
    env_broker = os.getenv("BROKER_TYPE", "SINOPAC").upper()

    parser = argparse.ArgumentParser(description="Arenax Price Downloader")

    parser.add_argument("-S", "--symbols", default=env_symbols,
                        help="Symbols to download (Default: WATCH_LIST env)")

    parser.add_argument("-B", "--broker", default=env_broker,
                        choices=["SINOPAC", "ARENAX"],
                        help="Broker type (Default: BROKER_TYPE env)")

    parser.add_argument("-s", "--start-date", default="2024-01-01",
                        help="Start date YYYY-MM-DD (Default: 2024-01-01)")

    parser.add_argument("-e", "--end-date", default="2024-06-30",
                        help="End date YYYY-MM-DD (Default: 2024-06-30)")

    args = parser.parse_args()
    if isinstance(args.symbols, str):
        args.symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    return args


def main():
    args = parse_args()

    if not args.symbols:
        print("No symbols specified. Use --symbols or set WATCH_LIST.")
        exit(1)

    load_supported_config_files()

    config = {
        "api_key": os.getenv("API_KEY"),
        "secret_key": os.getenv("SECRET_KEY"),
        "ca_path": os.getenv("CA_CERT_PATH"),
        "ca_passwd": os.getenv("CA_PASSWORD")
    }

    broker_type = BrokerType[args.broker]

    print(f"Starting download for {args.symbols} using {args.broker}...")
    print(f"Period: {args.start_date} to {args.end_date}")

    try:
        a = AccountClient(broker_type=broker_type, **config)
        a.connect()
        c = connect_sqlite(database="data/arenax_price.db")
        prepare_arenax_local_price_db_tables(conn=c)
        download_price(a, c, symbols=args.symbols,
                       start=args.start_date, end=args.end_date)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        c.close()
        a.disconnect()

# Example usage:
# uv run src/cjtrade/apps/ArenaX/tests/price_downloader.py --symbols=2330,2357 -s 2024-01-01 -e 2024-06-30
if __name__ == "__main__":
    main()
