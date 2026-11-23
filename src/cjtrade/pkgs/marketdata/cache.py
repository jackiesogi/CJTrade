"""PriceCache: the local SQLite price cache, as a MarketData.

The same file and tables ArenaX has always used (``paths.price_db_path()``),
so bars already downloaded are reused. It also records which windows have
been fetched ("coverage"), which is what lets :class:`Cached` tell a gap from
a window that simply has no trading in it.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import List
from typing import Optional
from typing import Tuple

from cjtrade.pkgs import paths
from cjtrade.pkgs.db import db_api
from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import INTERVALS
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar

_SCHEMA = Path(db_api.__file__).parent / "sql" / "create_arenax_local_price_db.sql"


class PriceCache(MarketData):
    """Bars stored on this machine. Never reaches the network.

    Parameters
    ----------
    path : str, optional
        SQLite file. Defaults to ``paths.price_db_path()``.

    Warnings
    --------
    Creates the file and its directory on first use. One SQLite connection is
    opened per thread.
    """

    name = "cache"

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else str(paths.price_db_path())
        self._local = threading.local()

    @property
    def conn(self):
        """The SQLite connection for the current thread, opened lazily."""
        if getattr(self._local, "conn", None) is None:
            conn = db_api.connect_sqlite(self.path)
            db_api.prepare_arenax_local_price_db_tables(conn=conn, script_path=str(_SCHEMA))
            self._local.conn = conn
        return self._local.conn

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(intervals=frozenset(INTERVALS))

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        """Return the cached bars in ``[start, end)``; never fetches."""
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        rows = db_api.get_price_from_arenax_local_price_db(
            conn=self.conn, symbol=symbol, timeframe=interval,
            start_ts=start_dt, end_ts=end_dt)
        # Several sources may hold the same bar; in_window keeps one.
        return in_window(rows, start_dt, end_dt)

    # ── what Cached needs ──────────────────────────────────────────────────

    def missing(self, symbol: str, interval: str, start: datetime,
                end: datetime) -> List[Tuple[datetime, datetime]]:
        """Sub-windows of ``[start, end)`` never fetched, as half-open pairs."""
        gaps = db_api.compute_missing_ranges(
            self.conn, symbol, interval,
            int(start.timestamp()), int(end.timestamp()) - 1)
        return [(datetime.fromtimestamp(s), datetime.fromtimestamp(e + 1))
                for s, e in gaps]

    def store(self, symbol: str, interval: str, kbars: List[Kbar],
              source: str) -> int:
        """Add bars without overwriting any already stored; returns how many landed."""
        landed = 0
        for k in kbars:
            if db_api.insert_price_to_arenax_local_price_db(
                    conn=self.conn, symbol=symbol, price=k, timeframe=interval,
                    source=source, overwrite=False):
                landed += 1
        return landed

    def mark_fetched(self, symbol: str, interval: str, start: datetime,
                     end: datetime, source: str) -> None:
        """Record ``[start, end)`` as fetched, clamped so it never reaches the future."""
        end = min(end, datetime.now())
        if end <= start:
            return
        db_api.upsert_coverage_range(
            self.conn, symbol, interval,
            int(start.timestamp()), int(end.timestamp()) - 1, source)
