"""Fetch exactly one (symbol, timeframe, range) through ArenaX and exit.

One call per process on purpose. Repeated get_kbars() calls inside a single
process were observed to make later calls return 0 bars for ranges that have
complete data, so the prewarm never loops in-process.

    ARENAX_PORT=8802 uv run python exp/bin/prewarm_one.py 2317 1m 2020-03-02 2021-01-01
"""
import logging
import sys

logging.basicConfig(level=logging.WARNING)

from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
from cjtrade.pkgs.models.product import Product


def main() -> int:
    sym, tf, start, end = sys.argv[1:5]
    api = ArenaXBrokerAPI_v2()
    try:
        bars = api.get_kbars(Product(symbol=sym), start, end, tf)
    except Exception as exc:
        print(f"{sym} {tf} {start}..{end} ERROR {type(exc).__name__}: {str(exc)[:120]}")
        return 1
    n = len(bars) if bars else 0
    first = bars[0].timestamp if n else "-"
    last = bars[-1].timestamp if n else "-"
    print(f"{sym} {tf} {start}..{end} bars={n} first={first} last={last}")
    return 0 if n else 2


if __name__ == "__main__":
    sys.exit(main())
