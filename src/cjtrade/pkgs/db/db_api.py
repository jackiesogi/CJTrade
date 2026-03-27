# TODO: Avoid SQL injection
# TODO: Add `Lock()`
from datetime import datetime
from datetime import timedelta
from typing import List
from typing import Optional

from cjtrade.pkgs.db.db_base import *
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import *

# Module-level connect functions
def connect_sqlite(database: str = ":memory:"):
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
        print(f"Failed to connect to SQLite database: {e}")


# def connect_duckdb(database: str = ":memory:"):
#     import duckdb
#     from cjtrade.pkgs.db.duckdb import DuckDBDatabaseConnection

#     if duckdb is None:
#         raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
#     conn = duckdb.connect(database=database)
#     return DuckDBDatabaseConnection(conn)

##########################   ArenaX-local-pricedb-specific CURD   ############################
DEFAUT_PREPARE_ARENAX_TABLE_SCRIPT = "./src/cjtrade/pkgs/db/sql/create_arenax_local_price_db.sql"

def prepare_arenax_local_price_db_tables(conn: DatabaseConnection = None):
    if conn is None:
        return
    try:
        with open(DEFAUT_PREPARE_ARENAX_TABLE_SCRIPT, 'r') as f:
            sql_script = f.read()
            conn.execute_script(sql_script)
        conn.commit()
        print("ArenaX local price tables are ready in local DB.")
    except Exception as e:
        print(f"Failed to prepare ArenaX local price tables in local DB: {e}")


# TODO: Support List[Kbar] batch insert for better performance
def insert_price_to_arenax_local_price_db(conn: DatabaseConnection = None,
                                          symbol: str = None,
                                          price: Kbar = None,
                                          timeframe: str = "1m",
                                          source: str = "unknown",
                                          overwrite: bool = True):
    """Insert a single Kbar into the local prices table.

    Returns True on success, False on failure.
    """
    if conn is None or symbol is None or price is None:
        return False

    try:
        # basic sanitization for SQL literals (escape single quotes)
        symbol_s = symbol.replace("'", "''")
        timeframe_s = (timeframe or '1m').replace("'", "''")
        source_s = (source or 'unknown').replace("'", "''")

        ts = int(price.timestamp.timestamp())
        open_p = float(price.open) if price.open is not None else 'NULL'
        high_p = float(price.high) if price.high is not None else 'NULL'
        low_p = float(price.low) if price.low is not None else 'NULL'
        close_p = float(price.close) if price.close is not None else 'NULL'
        volume_p = float(price.volume) if price.volume is not None else 'NULL'

        if overwrite:
            sqlcmd = f"""
                INSERT INTO arenax_prices (symbol, timeframe, ts, open, high, low, close, volume, source, adjusted, fetched_at)
                VALUES ('{symbol_s}', '{timeframe_s}', {ts}, {open_p}, {high_p}, {low_p}, {close_p}, {volume_p}, '{source_s}', 0, strftime('%s','now'))
                ON CONFLICT(symbol, timeframe, ts, source) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  fetched_at=excluded.fetched_at;
            """
        else:
            sqlcmd = f"""
                INSERT OR IGNORE INTO arenax_prices (symbol, timeframe, ts, open, high, low, close, volume, source, adjusted, fetched_at)
                VALUES ('{symbol_s}', '{timeframe_s}', {ts}, {open_p}, {high_p}, {low_p}, {close_p}, {volume_p}, '{source_s}', 0, strftime('%s','now'));
            """

        # ensure symbol exists in symbols table and update last_fetched
        # sql_symbol_insert = f"INSERT OR IGNORE INTO symbols (symbol, first_seen, last_fetched) VALUES ('{symbol_s}', {ts}, {ts});"
        # sql_symbol_update = f"UPDATE symbols SET last_fetched = {ts} WHERE symbol = '{symbol_s}' AND (last_fetched IS NULL OR last_fetched < {ts});"

        conn.execute(sqlcmd)
        # conn.execute(sql_symbol_insert)
        # conn.execute(sql_symbol_update)
        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to insert price for {symbol}: {e}")
        return False


# Get kbar data (List[Kbar]) for a symbol, [start_date, end_date]
# Granularity: 1day
def get_price_from_arenax_local_price_db(conn: DatabaseConnection = None,
                                         symbol: str = None,
                                         timeframe: str = "1m",
                                         start_ts: datetime = None,
                                         end_ts: datetime = None) -> List[Kbar]:
    results: List[Kbar] = []
    if conn is None or symbol is None:
        return results

    try:
        symbol_s = symbol.replace("'", "''")
        timeframe_s = (timeframe or '1m').replace("'", "''")

        where_clauses = [f"symbol = '{symbol_s}'", f"timeframe = '{timeframe_s}'"]
        if start_ts is not None:
            where_clauses.append(f"ts >= {int(start_ts.timestamp())}")
        if end_ts is not None:
            where_clauses.append(f"ts <= {int(end_ts.timestamp())}")

        where_sql = ' AND '.join(where_clauses)
        sqlcmd = f"SELECT ts, open, high, low, close, volume FROM arenax_prices WHERE {where_sql} ORDER BY ts ASC;"
        rows = conn.execute(sqlcmd)
        for r in rows:
            ts = int(r[0])
            o = float(r[1]) if r[1] is not None else 0.0
            h = float(r[2]) if r[2] is not None else 0.0
            l = float(r[3]) if r[3] is not None else 0.0
            c = float(r[4]) if r[4] is not None else 0.0
            v = int(r[5]) if r[5] is not None else 0
            k = Kbar(datetime.fromtimestamp(ts), o, h, l, c, v)
            results.append(k)
        return results
    except Exception as e:
        print(f"Failed to query prices for {symbol}: {e}")
        return results


##########################   CJTrade-specific CURD   ############################
from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection

DEFAUT_PREPARE_TABLE_SCRIPT="./src/cjtrade/pkgs/db/sql"
def prepare_cjtrade_tables(conn: SqliteDatabaseConnection = None):
    # Check if {orders,fills} table exists, if not create one
    if conn is None:
        return
    try:
        import os
        # Get all sql script path under DEFAUT_PREPARE_TABLE_SCRIPT
        sql_files = [f for f in os.listdir(DEFAUT_PREPARE_TABLE_SCRIPT) if f.endswith('.sql')]
        for sql_file in sql_files:
            sql_path = os.path.join(DEFAUT_PREPARE_TABLE_SCRIPT, sql_file)
            with open(sql_path, 'r') as f:
                sql_script = f.read()
                conn.execute_script(sql_script)
        conn.commit()
        print("Orders and Fills tables are ready in local DB.")
    except Exception as e:
        print(f"Failed to prepare orders and fills tables in local DB: {e}")

def insert_new_ordermap_item_to_db(conn: SqliteDatabaseConnection = None,
                                  cj_order_id: str = None,
                                  bkr_order_id: str = None,
                                  broker: str = None):
    if conn is None:
        return
    try:
        sqlcmd = f"INSERT INTO CJ_OrderMap (cj_order_id, broker_order_id, broker) VALUES ('{cj_order_id}', '{bkr_order_id}', '{broker}')"
        print(sqlcmd)
        conn.execute(sqlcmd)
        conn.commit()
    except Exception as e:
        print(f"Failed to insert order mapping for CJ order {cj_order_id} in local DB: {e}")

def get_bkr_order_id_from_db(conn: SqliteDatabaseConnection = None, cj_order_id: str = None) -> str:
    if conn is None:
        return None
    try:
        sqlcmd = f"SELECT broker_order_id FROM CJ_OrderMap WHERE cj_order_id = '{cj_order_id}'"
        print(sqlcmd)
        result = conn.execute(sqlcmd)
        if result:
            return result[0][0]  # TODO: this is currently a workaround for mal-design DB API that returns a tuple
        else:
            print(f"No mapping found for CJ order {cj_order_id} in local DB.")
            return None
    except Exception as e:
        print(f"Failed to get broker order ID for CJ order {cj_order_id} from local DB: {e}")
        return None

def get_cj_order_id_from_db(conn: SqliteDatabaseConnection = None, bkr_order_id: str = None) -> str:
    if conn is None:
        return None
    try:
        sqlcmd = f"SELECT cj_order_id FROM CJ_OrderMap WHERE broker_order_id = '{bkr_order_id}'"
        # print(sqlcmd)
        result = conn.execute(sqlcmd)
        if result:
            return result[0][0]  # TODO: this is currently a workaround for mal-design DB API that returns a tuple
        else:
            # print(f"No mapping found for broker order {bkr_order_id} in local DB.")
            return None
    except Exception as e:
        print(f"Failed to get CJ order ID for broker order {bkr_order_id} from local DB: {e}")
        return None

def insert_new_order_to_db(conn: SqliteDatabaseConnection = None,
                           username: str = 'user_unknown',
                           order: Order = None):
    if conn is None:
        return

    # Convert datetime to string format for SQLite
    created_at_str = order.created_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        sqlcmd = \
        f"""
            INSERT INTO orders (
              order_id, user_id, broker, product_id,
              side, order_type, price_type, price,
              quantity, status, created_at, updated_at
            )
            VALUES (
              '{order.id}', '{username}', '{order.broker}',
              '{order.product.symbol}', '{order.action}', '{order.order_type}',
              '{order.price_type}', '{order.price}', '{order.quantity}',
              'PLACED', '{created_at_str}', NULL
            )
        """
        print(sqlcmd)
        # Note that user default set to user_001 for simplicity
        conn.execute(sqlcmd)
        conn.commit()
        print(f"Order {order.id} inserted in local DB.")
    except Exception as e:
        print(f"Failed to insert order {order.id} in local DB: {e}")


def insert_new_order_to_db_legacy(conn: SqliteDatabaseConnection = None, order: Order = None):
    if conn is None:
        return

    # Convert datetime to string format for SQLite
    created_at_str = order.created_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        # TODO: How to pass user into this function?
        sqlcmd = \
        f"""
            INSERT INTO orders (
              order_id, user_id, broker, product_id,
              side, order_type, price_type, price,
              quantity, status, created_at, updated_at
            )
            VALUES (
              '{order.id}', 'user_123', '{order.broker}',
              '{order.product.symbol}', '{order.action}', '{order.order_type}',
              '{order.price_type}', '{order.price}', '{order.quantity}',
              'NEW', '{created_at_str}', NULL
            )
        """
        print(sqlcmd)
        # Note that user default set to user_001 for simplicity
        conn.execute(sqlcmd)
        conn.commit()
        print(f"Order {order.id} inserted in local DB.")
    except Exception as e:
        print(f"Failed to insert order {order.id} in local DB: {e}")

def update_order_status_to_db(conn: SqliteDatabaseConnection, oid: str, status: str, updated_at: datetime = datetime.utcnow() + timedelta(hours=8)):
    if conn is None:
        return

    updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        sqlcmd = \
        f"""
            UPDATE orders
            SET status = '{status}', updated_at = '{updated_at_str}'
            WHERE order_id = '{oid}'
        """
        print(sqlcmd)
        # Update status field ONLY
        conn.execute(sqlcmd)
        conn.commit()
        print(f"Order {oid} status updated to {status} in local DB.")
    except Exception as e:
        print(f"Failed to update order {oid} status in local DB: {e}")


# Simple test code
if __name__ == "__main__":
    from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection
    conn = connect_sqlite("./data/sinopac.db")
    res = get_cj_order_id_from_db(conn, "f224a302")
    print(type(res))
    print(res)
