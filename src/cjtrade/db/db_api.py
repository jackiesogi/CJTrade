from cjtrade.db.db_base import *
from cjtrade.models.order import *

# Module-level connect functions
def connect_sqlite(database: str = ":memory:"):
    import sqlite3
    from cjtrade.db.sqlite import SqliteDatabaseConnection

    try:
        conn = sqlite3.connect(database)
        return SqliteDatabaseConnection(conn)
    except ConnectionError as e:
        print(f"Failed to connect to SQLite database: {e}")


# def connect_duckdb(database: str = ":memory:"):
#     import duckdb
#     from cjtrade.db.duckdb import DuckDBDatabaseConnection

#     if duckdb is None:
#         raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
#     conn = duckdb.connect(database=database)
#     return DuckDBDatabaseConnection(conn)


##########################   CJTrade-specific CURD   ############################
from cjtrade.db.sqlite import SqliteDatabaseConnection

DEFAUT_PREPARE_TABLE_SCRIPT="./src/cjtrade/db/sql"
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


def insert_new_order_to_db(conn: SqliteDatabaseConnection = None, order: Order = None):
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

def update_order_status_to_db(conn: SqliteDatabaseConnection, oid: str, status: str):
    if conn is None:
        return

    try:
        # Update status field ONLY
        conn.execute(
        f"""
            UPDATE orders
            SET status = '{status}', updated_at = CURRENT_TIMESTAMP
            WHERE order_id = '{oid}'
        """
        )
        conn.commit()
        print(f"Order {oid} status updated to {status} in local DB.")
    except Exception as e:
        print(f"Failed to update order {oid} status in local DB: {e}")