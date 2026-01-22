from cjtrade.db.db_base import *

# Module-level connect functions
def connect_sqlite(database: str = ":memory:"):
    import sqlite3
    from cjtrade.db.sqlite import SqliteDatabaseConnection

    conn = sqlite3.connect(database)
    return SqliteDatabaseConnection(conn)


# def connect_duckdb(database: str = ":memory:"):
#     import duckdb
#     from cjtrade.db.duckdb import DuckDBDatabaseConnection

#     if duckdb is None:
#         raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
#     conn = duckdb.connect(database=database)
#     return DuckDBDatabaseConnection(conn)