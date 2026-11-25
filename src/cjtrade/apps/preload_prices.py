"""
apps/preload_prices.py
~~~~~~~~~~~~~~~~~~~~~~
Download bars into a price cache file, so ArenaX can run on it offline.

    preload-prices --price-db exp.db --symbols 2330,2317 \\
                   --start 2025-09-01 --end 2025-10-01
    arenaxd --backend backtest --data offline --price-db exp.db

The window is half-open: ``--end 2025-10-01`` stops before 1 October.
Only windows the file lacks are fetched, so running it again tops a file up
rather than downloading everything twice. Bars still forming are never
stored, so a file filled during a session holds complete bars only.

The file is the same SQLite format as the default cache
(``paths.price_db_path()``); point ``--price-db`` at a new path to get a
clean one that holds exactly what was asked for.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from datetime import timedelta
from typing import List
from typing import Optional

from cjtrade.pkgs import paths
from cjtrade.pkgs.marketdata import Cached
from cjtrade.pkgs.marketdata import PriceCache
from cjtrade.pkgs.marketdata.base import INTERVALS
from cjtrade.pkgs.marketdata.base import MarketDataError
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.marketdata.factory import from_names
from cjtrade.pkgs.marketdata.factory import parse_names


def _sinopac_broker():
    """A connected Sinopac client, configured the way arenaxd configures it."""
    from cjtrade.apps.ArenaX.brokerside_server import external_config
    from cjtrade.apps.ArenaX.brokerside_server import load_cjconf
    from cjtrade.pkgs.brokers.account_client import AccountClient
    from cjtrade.pkgs.brokers.account_client import BrokerType
    load_cjconf()
    client = AccountClient(broker_type=BrokerType.SINOPAC, **external_config)
    client.connect()
    return client


def preload(price_db: str, data: str, symbols: List[str], start: str, end: str,
            intervals: List[str]) -> int:
    """Fill `price_db` with `symbols`' bars in ``[start, end)``; returns how many are there."""
    names = parse_names(data)
    if "offline" in names or names == ["cache"]:
        raise ValueError("preload needs a source that downloads: sinopac, finmind or yfinance")
    sinopac = _sinopac_broker() if "sinopac" in names else None
    store = PriceCache(price_db)
    market = from_names(names, sinopac=sinopac, cache=False, cache_path=price_db)
    cached = Cached(market, store)
    start_dt, end_dt = to_window(start, end)
    total = 0
    try:
        for symbol in symbols:
            for interval in intervals:
                try:
                    bars = cached.get_kbars(symbol, start_dt, end_dt, interval)
                except MarketDataError as e:
                    print(f"{symbol} {interval}: skipped ({e})")
                    continue
                total += len(bars)
                days = len({b.timestamp.date() for b in bars})
                span = (f"{bars[0].timestamp:%Y-%m-%d %H:%M} .. {bars[-1].timestamp:%Y-%m-%d %H:%M}"
                        if bars else "none")
                print(f"{symbol} {interval}: {len(bars)} bars over {days} days ({span})")
    finally:
        store.close()
        if sinopac is not None:
            sinopac.disconnect()
    return total


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preload-prices",
        description="Download bars into a price cache file for offline ArenaX runs.")
    parser.add_argument("--price-db", default=None,
                        help="SQLite file to fill (created if missing). "
                             "Defaults to the shared cache file.")
    parser.add_argument("--data", default="finmind,yfinance",
                        help="Sources in order (sinopac, finmind, yfinance). "
                             "Default: finmind,yfinance.")
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. 2330,2317.")
    parser.add_argument("--start", required=True, help="First day, YYYY-MM-DD.")
    parser.add_argument("--end", default=None,
                        help="Day to stop before, YYYY-MM-DD. Default: tomorrow, "
                             "so today's closed bars are included.")
    parser.add_argument("--interval", default="1m,5m,1h,1d",
                        help=f"Comma-separated, from {', '.join(INTERVALS)}. Default: "
                             "1m,5m,1h,1d, every interval the ArenaX kbars route serves. "
                             "An offline server only has what was preloaded.")
    args = parser.parse_args(argv)

    price_db = args.price_db or str(paths.price_db_path())
    end = args.end or (date.today() + timedelta(days=1)).isoformat()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    intervals = [i.strip() for i in args.interval.split(",") if i.strip()]
    bad = [i for i in intervals if i not in INTERVALS]
    if bad or not symbols:
        parser.error(f"unknown interval(s) {bad}" if bad else "no symbols given")
    try:
        total = preload(price_db, args.data, symbols, args.start, end, intervals)
    except ValueError as e:
        parser.error(str(e))
    print(f"{total} bars in {price_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
