# TODO: Add `Lock()`
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import List
from typing import Optional

from cjtrade.pkgs.db.db_base import *
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import *

log = get_logger("db")

_SQL_DIR = Path(__file__).resolve().parent / "sql"

# Module-level connect functions
def connect_sqlite(database: str = ":memory:"):
    """Open a SQLite database and wrap it in a `SqliteDatabaseConnection`.

    Opened with ``check_same_thread=False`` so broker callbacks on other
    threads can use it.

    Parameters
    ----------
    database : str
        File path (``~`` is expanded) or ``":memory:"``.

    Returns
    -------
    SqliteDatabaseConnection or None
        None if a ConnectionError was caught; the error is logged.

    Warnings
    --------
    Creates the parent directory of `database` if missing, and the
    database file itself.
    """
    import sqlite3
    from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection

    try:
        # Allow cross-thread access for Shioaji callbacks
        # SQLite is still thread-safe as long as we don't have concurrent writes
        import os
        db_path = os.path.expanduser(database)
        if db_path != ":memory:":
            db_path = os.path.abspath(db_path)
            parent_dir = os.path.dirname(db_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteDatabaseConnection(conn)
    except ConnectionError as e:
        log.error("SQLite conn failed: %s", e)


# def connect_duckdb(database: str = ":memory:"):
#     import duckdb
#     from cjtrade.pkgs.db.duckdb import DuckDBDatabaseConnection

#     if duckdb is None:
#         raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
#     conn = duckdb.connect(database=database)
#     return DuckDBDatabaseConnection(conn)

##########################   ArenaX-local-pricedb-specific CURD   ############################
# Beside this module, so the scripts are found whatever the working directory
# and in an installed package, not only from a checkout's root.
DEFAUT_PREPARE_ARENAX_TABLE_SCRIPT = str(_SQL_DIR / "create_arenax_local_price_db.sql")

def prepare_arenax_local_price_db_tables(conn: DatabaseConnection = None, script_path: str = None):
    """Create the ArenaX local price tables by running a SQL script.

    Parameters
    ----------
    conn : DatabaseConnection, optional
        Target database; does nothing if None.
    script_path : str, optional
        Defaults to `DEFAUT_PREPARE_ARENAX_TABLE_SCRIPT`, the script shipped
        with this package.

    Warnings
    --------
    Writes to the database. Errors are logged, not raised.
    """
    if conn is None:
        return
    if script_path is None:
        script_path = DEFAUT_PREPARE_ARENAX_TABLE_SCRIPT
    try:
        with open(script_path, 'r') as f:
            sql_script = f.read()
            conn.execute_script(sql_script)
        conn.commit()
        # _migrate_coverage_table_if_needed(conn)
        log.debug("ArenaX local price tables ready")
    except Exception as e:
        log.error("prepare ArenaX local price tables failed: %s", e)



# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge a list of (start, end) integer intervals, returning sorted, non-overlapping list."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[int, int]] = [sorted_ivs[0]]
    for s, e in sorted_ivs[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e + 1:          # adjacent or overlapping – extend
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def get_coverage_ranges(conn: DatabaseConnection,
                        symbol: str,
                        timeframe: str = "1m") -> list[tuple[int, int]]:
    """Return sorted, merged list of (start_ts, end_ts) epoch-second tuples for a symbol."""
    rows = conn.execute(
        "SELECT start_ts, end_ts FROM arenax_symbol_coverage "
        "WHERE symbol=? AND timeframe=? ORDER BY start_ts ASC",
        (symbol, timeframe)
    )
    if not rows:
        return []
    return _merge_intervals([(int(r[0]), int(r[1])) for r in rows])


def compute_missing_ranges(conn: DatabaseConnection,
                           symbol: str,
                           timeframe: str,
                           start_ts: int,
                           end_ts: int) -> list[tuple[int, int]]:
    """Return list of (start_ts, end_ts) sub-intervals of [start_ts, end_ts] NOT in cache.

    Parameters
    ----------
    conn : DatabaseConnection
        Database holding ``arenax_symbol_coverage``.
    symbol : str
        Ticker.
    timeframe : str
        Bar timeframe, e.g. ``"1m"``.
    start_ts, end_ts : int
        Unix epoch seconds (inclusive on both ends).

    Returns
    -------
    list of tuple of int
        Gap intervals that need to be fetched.
    """
    covered = get_coverage_ranges(conn, symbol, timeframe)
    gaps: list[tuple[int, int]] = []
    cursor = start_ts
    for cov_s, cov_e in covered:
        if cov_s > end_ts:
            break                        # covered range is entirely after request window
        if cov_e < cursor:
            continue                     # covered range is entirely before current cursor
        if cov_s > cursor:
            gaps.append((cursor, cov_s - 1))   # gap before this covered interval
        cursor = max(cursor, cov_e + 1)
    if cursor <= end_ts:
        gaps.append((cursor, end_ts))   # trailing gap
    return gaps


def upsert_coverage_range(conn: DatabaseConnection,
                          symbol: str,
                          timeframe: str,
                          start_ts: int,
                          end_ts: int,
                          source: str = "unknown"):
    """Insert a new covered interval and consolidate overlapping rows for cleanliness.

    This uses an insert-then-compact strategy:
      1. Insert the new row.
      2. Find all rows (including the new one) that overlap/touch the new interval.
      3. Merge them into a single row; delete the originals.
    This keeps the table tidy even after many incremental fetches.
    Does nothing if ``start_ts > end_ts``.

    Warnings
    --------
    Inserts, updates and deletes rows in ``arenax_symbol_coverage`` and
    commits. ``last_checked`` and ``created_at`` come from the wall clock.
    """
    if start_ts > end_ts:
        return

    now = int(datetime.utcnow().timestamp())

    # 1. Insert new range
    conn.execute(
        "INSERT INTO arenax_symbol_coverage (symbol, timeframe, start_ts, end_ts, source, last_checked, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (symbol, timeframe, start_ts, end_ts, source, now, now)
    )
    conn.commit()

    # 2. Find all rows that overlap or are adjacent to [start_ts, end_ts]
    rows = conn.execute(
        "SELECT id, start_ts, end_ts FROM arenax_symbol_coverage "
        "WHERE symbol=? AND timeframe=? AND start_ts <= ? AND end_ts >= ? "
        "ORDER BY start_ts ASC",
        (symbol, timeframe, end_ts + 1, start_ts - 1)
    )
    if not rows or len(rows) <= 1:
        return  # nothing to consolidate

    # 3. Merge all found rows into one
    ids     = [r[0] for r in rows]
    merged_s = min(r[1] for r in rows)
    merged_e = max(r[2] for r in rows)

    keep_id = ids[-1]
    delete_ids = ids[:-1]

    conn.execute(
        "UPDATE arenax_symbol_coverage SET start_ts=?, end_ts=?, last_checked=? WHERE id=?",
        (merged_s, merged_e, now, keep_id)
    )
    placeholders = ",".join("?" for _ in delete_ids)
    conn.execute(
        f"DELETE FROM arenax_symbol_coverage WHERE id IN ({placeholders})",
        tuple(delete_ids)
    )
    conn.commit()


# TODO: Support List[Kbar] batch insert for better performance
def insert_price_to_arenax_local_price_db(conn: DatabaseConnection = None,
                                          symbol: str = None,
                                          price: Kbar = None,
                                          timeframe: str = "1m",
                                          source: str = "unknown",
                                          overwrite: bool = True):
    """Insert a single Kbar into the local prices table.

    Parameters
    ----------
    conn : DatabaseConnection, optional
        Target database.
    symbol : str, optional
        Ticker.
    price : Kbar, optional
        The bar to store.
    timeframe : str
        Bar timeframe, ``"1m"`` by default.
    source : str
        Data source label, part of the row's key.
    overwrite : bool
        If True, replace an existing row with the same
        (symbol, timeframe, ts, source); otherwise keep it.

    Returns
    -------
    bool
        True on success, False on failure or if `conn`, `symbol` or
        `price` is None.

    Warnings
    --------
    Writes and commits. ``fetched_at`` is the wall-clock time. Errors are
    logged, not raised.
    """
    if conn is None or symbol is None or price is None:
        return False

    try:
        ts = int(price.timestamp.timestamp())
        open_p = float(price.open) if price.open is not None else None
        high_p = float(price.high) if price.high is not None else None
        low_p = float(price.low) if price.low is not None else None
        close_p = float(price.close) if price.close is not None else None
        volume_p = float(price.volume) if price.volume is not None else None
        tf = timeframe or '1m'
        src = source or 'unknown'

        if overwrite:
            conn.execute(
                "INSERT INTO arenax_prices (symbol, timeframe, ts, open, high, low, close, volume, source, adjusted, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, strftime('%s','now')) "
                "ON CONFLICT(symbol, timeframe, ts, source) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, "
                "close=excluded.close, volume=excluded.volume, fetched_at=excluded.fetched_at",
                (symbol, tf, ts, open_p, high_p, low_p, close_p, volume_p, src)
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO arenax_prices (symbol, timeframe, ts, open, high, low, close, volume, source, adjusted, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, strftime('%s','now'))",
                (symbol, tf, ts, open_p, high_p, low_p, close_p, volume_p, src)
            )

        conn.commit()
        return True
    except Exception as e:
        log.error("insert price for %s failed: %s", symbol, e)
        return False


# Get kbar data (List[Kbar]) for a symbol, [start_date, end_date]
# Granularity: 1day
def get_price_from_arenax_local_price_db(conn: DatabaseConnection = None,
                                         symbol: str = None,
                                         timeframe: str = "1m",
                                         start_ts: datetime = None,
                                         end_ts: datetime = None) -> List[Kbar]:
    """Return the stored bars of `symbol` between `start_ts` and `end_ts`, oldest first.

    Parameters
    ----------
    conn : DatabaseConnection, optional
        Source database; returns ``[]`` if None.
    symbol : str, optional
        Ticker; returns ``[]`` if None.
    timeframe : str
        Bar timeframe, ``"1m"`` by default.
    start_ts, end_ts : datetime, optional
        Inclusive bounds; None leaves that side open.

    Returns
    -------
    list of Kbar
        Timestamps are naive local time (``datetime.fromtimestamp``);
        NULL prices and volumes become 0. Empty on error (logged).
    """
    results: List[Kbar] = []
    if conn is None or symbol is None:
        return results

    try:
        where_clauses = ["symbol = ?", "timeframe = ?"]
        params = [symbol, timeframe or '1m']
        if start_ts is not None:
            where_clauses.append("ts >= ?")
            params.append(int(start_ts.timestamp()))
        if end_ts is not None:
            where_clauses.append("ts <= ?")
            params.append(int(end_ts.timestamp()))

        where_sql = ' AND '.join(where_clauses)
        sql = f"SELECT ts, open, high, low, close, volume FROM arenax_prices WHERE {where_sql} ORDER BY ts ASC;"
        rows = conn.execute(sql, tuple(params))
        for r in rows:
            ts = int(r[0])
            o = float(r[1]) if r[1] is not None else 0.0
            h = float(r[2]) if r[2] is not None else 0.0
            l = float(r[3]) if r[3] is not None else 0.0
            c = float(r[4]) if r[4] is not None else 0.0
            v = int(r[5]) if r[5] is not None else 0
            k = Kbar(datetime.fromtimestamp(ts), o, h, l, c, v, symbol)
            results.append(k)
        return results
    except Exception as e:
        log.error("query prices for %s failed: %s", symbol, e)
        return results


##########################   CJTrade-specific CURD   ############################
from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection

DEFAUT_PREPARE_TABLE_SCRIPT = str(_SQL_DIR)
def prepare_cjtrade_tables(conn: SqliteDatabaseConnection = None, sql_dir: str = None):
    """Create the CJTrade tables by running every ``.sql`` file in `sql_dir`.

    Parameters
    ----------
    conn : SqliteDatabaseConnection, optional
        Target database; does nothing if None.
    sql_dir : str, optional
        Defaults to `DEFAUT_PREPARE_TABLE_SCRIPT`, the scripts shipped with
        this package.

    Warnings
    --------
    Writes to the database. Errors are logged, not raised.
    """
    # Check if {orders,fills} table exists, if not create one
    if conn is None:
        return
    if sql_dir is None:
        sql_dir = DEFAUT_PREPARE_TABLE_SCRIPT
    try:
        import os
        # Get all sql script path under sql_dir
        sql_files = [f for f in os.listdir(sql_dir) if f.endswith('.sql')]
        for sql_file in sql_files:
            sql_path = os.path.join(sql_dir, sql_file)
            with open(sql_path, 'r') as f:
                sql_script = f.read()
                conn.execute_script(sql_script)
        conn.commit()
        log.debug("orders and fills tables ready")
    except Exception as e:
        log.error("prepare orders and fills tables failed: %s", e)

def insert_new_ordermap_item_to_db(conn: SqliteDatabaseConnection = None,
                                  cj_order_id: str = None,
                                  bkr_order_id: str = None,
                                  broker: str = None):
    """Record which broker order id a CJ order id maps to, in ``CJ_OrderMap``.

    This mapping is the only link from a CJTrade order to the broker's order.

    Parameters
    ----------
    conn : SqliteDatabaseConnection, optional
        Target database; does nothing if None.
    cj_order_id : str, optional
        CJTrade order id.
    bkr_order_id : str, optional
        Broker order id.
    broker : str, optional
        Broker name.

    Warnings
    --------
    Writes and commits. Errors are logged, not raised, so the caller is
    not told when a mapping is lost.
    """
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO CJ_OrderMap (cj_order_id, broker_order_id, broker) VALUES (?, ?, ?)",
            (cj_order_id, bkr_order_id, broker)
        )
        conn.commit()
    except Exception as e:
        log.error("insert order map for CJ order %s failed: %s", cj_order_id, e)

def get_bkr_order_id_from_db(conn: SqliteDatabaseConnection = None, cj_order_id: str = None) -> str:
    """Return the broker order id mapped to `cj_order_id`.

    Returns
    -------
    str or None
        None if `conn` is None, no mapping exists, or the query fails
        (the error is logged).
    """
    if conn is None:
        return None
    try:
        result = conn.execute(
            "SELECT broker_order_id FROM CJ_OrderMap WHERE cj_order_id = ?",
            (cj_order_id,)
        )
        if result:
            return result[0][0]
        else:
            log.warning("no order map for CJ order %s", cj_order_id)
            return None
    except Exception as e:
        log.error("get broker order id for CJ order %s failed: %s", cj_order_id, e)
        return None

def get_cj_order_id_from_db(conn: SqliteDatabaseConnection = None, bkr_order_id: str = None) -> str:
    """Return the CJ order id mapped to `bkr_order_id`.

    Returns
    -------
    str or None
        None if `conn` is None, no mapping exists, or the query fails
        (the error is logged).
    """
    if conn is None:
        return None
    try:
        result = conn.execute(
            "SELECT cj_order_id FROM CJ_OrderMap WHERE broker_order_id = ?",
            (bkr_order_id,)
        )
        if result:
            return result[0][0]
        else:
            return None
    except Exception as e:
        log.error("get CJ order id for broker order %s failed: %s", bkr_order_id, e)
        return None

def insert_new_order_to_db(conn: SqliteDatabaseConnection = None,
                           username: str = 'user_unknown',
                           order: Order = None):
    """Insert `order` into the ``orders`` table with status ``'PLACED'``.

    Parameters
    ----------
    conn : SqliteDatabaseConnection, optional
        Target database; does nothing if None.
    username : str
        Stored as ``user_id``.
    order : Order
        Required despite the None default.

    Warnings
    --------
    Writes and commits. Database errors are logged, not raised.
    """
    if conn is None:
        return

    # Convert datetime to string format for SQLite
    created_at_str = order.created_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn.execute(
            "INSERT INTO orders ("
            "  order_id, user_id, broker, product_id,"
            "  side, order_type, price_type, price,"
            "  quantity, status, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PLACED', ?, NULL)",
            (order.id, username, order.broker, order.product.symbol,
             order.action, order.order_type, order.price_type, order.price,
             order.quantity, created_at_str)
        )
        conn.commit()
        log.debug("@%s order %s inserted", created_at_str[:16], order.id)
    except Exception as e:
        log.error("@%s insert order %s failed: %s", created_at_str[:16], order.id, e)


def insert_new_order_to_db_legacy(conn: SqliteDatabaseConnection = None, order: Order = None):
    """Legacy form of `insert_new_order_to_db`.

    Stores ``user_id='user_123'`` and status ``'NEW'``.

    Warnings
    --------
    Legacy and unused in this repo. Writes and commits; errors are logged,
    not raised.
    """
    if conn is None:
        return

    # Convert datetime to string format for SQLite
    created_at_str = order.created_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn.execute(
            "INSERT INTO orders ("
            "  order_id, user_id, broker, product_id,"
            "  side, order_type, price_type, price,"
            "  quantity, status, created_at, updated_at"
            ") VALUES (?, 'user_123', ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, NULL)",
            (order.id, order.broker, order.product.symbol, order.action,
             order.order_type, order.price_type, order.price, order.quantity,
             created_at_str)
        )
        conn.commit()
        log.debug("@%s order %s inserted", created_at_str[:16], order.id)
    except Exception as e:
        log.error("@%s insert order %s failed: %s", created_at_str[:16], order.id, e)

def update_order_status_to_db(conn: SqliteDatabaseConnection, oid: str, status: str, updated_at: datetime = datetime.utcnow() + timedelta(hours=8)):
    """Set ``status`` and ``updated_at`` of order `oid` in the ``orders`` table.

    Parameters
    ----------
    conn : SqliteDatabaseConnection
        Target database; does nothing if None.
    oid : str
        CJ order id.
    status : str
        New status.
    updated_at : datetime, optional
        Stored as ``"%Y-%m-%d %H:%M:%S"``.

    Warnings
    --------
    The `updated_at` default (``datetime.utcnow() + 8h``) is evaluated once
    at import time, so every call that omits it stores the module load time.
    Writes and commits; errors are logged, not raised.
    """
    if conn is None:
        return

    updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
            (status, updated_at_str, oid)
        )
        conn.commit()
        log.debug("@%s order %s status -> %s", updated_at_str[:16], oid, status)
    except Exception as e:
        log.error("@%s update order %s status failed: %s", updated_at_str[:16], oid, e)


# Simple test code
if __name__ == "__main__":
    from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection
    from cjtrade.pkgs.logger import get_console
    from cjtrade.pkgs.logger import setup_logging
    setup_logging()
    out = get_console()
    conn = connect_sqlite(str(paths.mirror_db_path("sinopac")))
    res = get_cj_order_id_from_db(conn, "f224a302")
    out.info("%s", type(res))
    out.info("%s", res)
