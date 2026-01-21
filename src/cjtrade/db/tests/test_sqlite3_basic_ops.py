from cjtrade.db.models.database import *
from cjtrade.db.tests.utils import _clean_up_test_db, TEST_DB_PATH, db_shell


def test_is_connected():
    config = {"database": TEST_DB_PATH}
    db = SqliteDatabase(**config)
    assert db.is_connected() == False
    db.connect()
    assert db.is_connected() == True
    db.disconnect()
    assert db.is_connected() == False

def test_execute():
    config = {"database": TEST_DB_PATH}
    db = SqliteDatabase(**config)

    # Test without connection should raise exception
    try:
        db.execute("SELECT 1;")
        assert False, "Expected exception for executing without connection."
    except Exception as e:
        assert str(e) == "Database is not connected."

    db.connect()
    db.execute("CREATE TABLE IF NOT EXISTS member (id INTEGER PRIMARY KEY, name TEXT, age INTEGER, email TEXT);")
    db.execute("INSERT INTO member (name, age, email) VALUES ('Alice', 30, 'alice@example.com');")
    db.execute("INSERT INTO member (name, age, email) VALUES ('Bob', 25, 'bob@example.com');")
    db.commit()

    # Show column names using PRAGMA
    pragma_results = db.execute("PRAGMA table_info(member);")
    # pragma_results rows: (cid, name, type, notnull, dflt_value, pk)
    column_names = [row[1] for row in pragma_results]
    # For visibility when running script directly, print column names
    print("Column names:", column_names)
    # Ensure the expected columns exist
    assert column_names == ['id', 'name', 'age', 'email']

    # Query data
    results = db.execute("SELECT * FROM member;")
    assert len(results) == 2
    assert results[0][1] == 'Alice'
    assert results[0][2] == 30
    assert results[0][3] == 'alice@example.com'
    assert results[1][1] == 'Bob'
    assert results[1][2] == 25
    assert results[1][3] == 'bob@example.com'
    db.disconnect()



if __name__ == "__main__":
    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<

    test_is_connected()
    test_execute()

    config = {"database": TEST_DB_PATH}
    db = SqliteDatabase(**config)
    db.connect()
    db_shell(db)
    db.disconnect()

    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<
