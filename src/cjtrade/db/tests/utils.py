from cjtrade.db.db_base import *
from cjtrade.db.sqlite import SqliteDatabaseConnection

TEST_DB_PATH = "src/cjtrade/db/tests/test_sqlite3_ops.db"
MAX_HISTORY_SIZE = 30

def _clean_up_test_db():
    import os
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


def db_shell(db: SqliteDatabaseConnection):
    try:
        import readline
    except ImportError:
        import pyreadline3 as readline

    def init_readline():
        readline.set_history_length(MAX_HISTORY_SIZE)
        readline.parse_and_bind("tab: complete")

    init_readline()

    # Add two helper commands to history
    readline.add_history("select * from non_existing_table")
    readline.add_history("select * from transaction_history")
    readline.add_history("select * from member")
    readline.add_history("select * from fills")

    while True:
        cmd = input("db> ")
        if cmd.lower() in ["exit", "quit"]:
            print("Bye! Cleaning up...")
            break
        try:
            readline.add_history(cmd)
            results = db.execute(cmd)
            for row in results:
                print(row)
        except Exception as e:
            print(f"Error: {e}")
