from cjtrade.db.db_base import *
from cjtrade.db.db_api import connect_sqlite
from cjtrade.db.sqlite import *
from cjtrade.db.tests.utils import _clean_up_test_db, TEST_DB_PATH, db_shell
try:
    import readline
except ImportError:
    import pyreadline3 as readline


def test_create_fill_ledger_sql():
    conn = connect_sqlite(TEST_DB_PATH)
    # Load and execute the SQL script to create the fills table
    with open("src/cjtrade/db/sql/create_fill_ledger.sql", "r") as f:
        sql_script = f.read()
    conn.execute_script(sql_script)
    conn.commit()


def test_create_order_ledger_sql():
    conn = connect_sqlite(TEST_DB_PATH)
    # Load and execute the SQL script to create the orders table
    with open("src/cjtrade/db/sql/create_order_ledger.sql", "r") as f:
        sql_script = f.read()
    conn.execute_script(sql_script)
    conn.commit()

if __name__ == "__main__":
    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<

    test_create_fill_ledger_sql()
    test_create_order_ledger_sql()

    db = connect_sqlite(TEST_DB_PATH)
    db_shell(db)
    db.close()

    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<
