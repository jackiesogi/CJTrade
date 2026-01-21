from dataclasses import dataclass
import json
from cjtrade.models.order import *
from cjtrade.db.models.database import *
from cjtrade.db.tests.utils import _clean_up_test_db, db_shell, TEST_DB_PATH
from typing import Any, Dict

# This is a dummy class for testing purposes,
# DO NOT mess with actual HistoryEntry class in production code.
@dataclass
class HistoryEntry:
    record_id: int
    timestamp: str
    cost: float
    quantity: int
    original_order: Order  # or using linked_order
    type: str
    action: OrderAction
    details: Dict[str, Any]


def test_add_history_entry(conn: SqliteDatabaseConnection, entry: HistoryEntry):
    # Helper to quote and escape strings for SQL literals
    def q(s: str) -> str:
        if s is None:
            return 'NULL'
        return "'" + str(s).replace("'", "''") + "'"

    # Prepare SQL-safe literals
    timestamp = q(entry.timestamp)
    original_order = q(repr(entry.original_order))
    type_field = q(entry.type)
    action_field = q(getattr(entry.action, 'value', str(entry.action)))
    details = q(json.dumps(entry.details))

    sql = f"""
    INSERT INTO transaction_history
    (record_id, timestamp, cost, quantity, original_order, type, action, details)
    VALUES ({entry.record_id},
        {timestamp},
        {entry.cost},
        {entry.quantity},
        {original_order},
        {type_field},
        {action_field},
        {details});
    """
    conn.execute(sql)
    conn.commit()



def test_execute_history_entry_load_store():
    db = connect_sqlite(TEST_DB_PATH)
    db.execute("""
    CREATE TABLE IF NOT EXISTS transaction_history (
        record_id INTEGER PRIMARY KEY,
        timestamp TEXT,
        cost REAL,
        quantity INTEGER,
        original_order TEXT,
        type TEXT,
        action TEXT,
        details TEXT
    );""")
    db.commit()

    # Create a sample HistoryEntry
    sample_entry = HistoryEntry(
        record_id=1,
        timestamp="2024-01-01T12:00:00Z",
        cost=100.5,
        quantity=10,
        original_order=Order(product=Product(symbol="0050"),
                             action=OrderAction.BUY,
                             quantity=10,
                             price=100.5,
                             order_lot=OrderLot.IntraDayOdd,
                             order_type=OrderType.ROD,
                             price_type=PriceType.LMT),
        type="BUY",
        action=OrderAction.BUY,
        details={"note": "Test entry"}
    )
    test_add_history_entry(db, sample_entry)
    db.close()


if __name__ == "__main__":
    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<

    db = connect_sqlite(TEST_DB_PATH)
    test_execute_history_entry_load_store()
    db_shell(db)
    db.close()

    _clean_up_test_db() # <<<<<<<<<<<<<<<<<<<