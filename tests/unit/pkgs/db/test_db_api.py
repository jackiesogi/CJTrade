"""Unit tests for cjtrade.pkgs.db — uses in-memory SQLite, no file I/O."""
import sqlite3
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.db.db_api import _merge_intervals
from cjtrade.pkgs.db.db_api import compute_missing_ranges
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import get_bkr_order_id_from_db
from cjtrade.pkgs.db.db_api import get_cj_order_id_from_db
from cjtrade.pkgs.db.db_api import get_coverage_ranges
from cjtrade.pkgs.db.db_api import get_price_from_arenax_local_price_db
from cjtrade.pkgs.db.db_api import insert_new_order_to_db
from cjtrade.pkgs.db.db_api import insert_new_ordermap_item_to_db
from cjtrade.pkgs.db.db_api import insert_price_to_arenax_local_price_db
from cjtrade.pkgs.db.db_api import update_order_status_to_db
from cjtrade.pkgs.db.db_api import upsert_coverage_range
from cjtrade.pkgs.db.sqlite import SqliteDatabaseConnection
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """In-memory SQLite connection with all tables prepared."""
    conn = connect_sqlite(":memory:")
    # Create tables inline (no file dependency)
    conn.execute_script("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            product_id TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price_type TEXT NOT NULL,
            price REAL,
            quantity INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            user_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            product_id TEXT NOT NULL,
            side TEXT NOT NULL,
            filled_price REAL NOT NULL,
            filled_quantity INTEGER NOT NULL,
            filled_time TEXT NOT NULL,
            received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS CJ_OrderMap (
            cj_order_id TEXT PRIMARY KEY,
            broker_order_id TEXT NOT NULL,
            broker TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ordermap_broker_order_id
            ON CJ_OrderMap(broker_order_id);
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def price_db():
    """In-memory SQLite connection with ArenaX price tables."""
    conn = connect_sqlite(":memory:")
    conn.execute_script("""
        CREATE TABLE IF NOT EXISTS arenax_prices (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            ts INTEGER NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            source TEXT NOT NULL,
            adjusted INTEGER DEFAULT 0,
            fetched_at INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0,
            PRIMARY KEY (symbol, timeframe, ts, source)
        );
        CREATE TABLE IF NOT EXISTS arenax_symbol_coverage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'unknown',
            last_checked INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_coverage_symbol_tf_start
            ON arenax_symbol_coverage(symbol, timeframe, start_ts);
    """)
    conn.commit()
    yield conn
    conn.close()


def _make_order(**kwargs):
    defaults = dict(
        product=Product(symbol="0050"),
        action=OrderAction.BUY,
        price=55.0,
        quantity=10,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD,
        order_lot=OrderLot.Common,
        broker="arenax",
    )
    defaults.update(kwargs)
    return Order(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# SqliteDatabaseConnection
# ═══════════════════════════════════════════════════════════════════════════════

class TestSqliteDatabaseConnection:
    def test_execute_basic(self, db):
        rows = db.execute("SELECT 1+1")
        assert rows == [(2,)]

    def test_execute_with_params(self, db):
        rows = db.execute("SELECT ? + ?", (3, 4))
        assert rows == [(7,)]

    def test_close_prevents_further_use(self):
        conn = connect_sqlite(":memory:")
        conn.close()
        with pytest.raises(Exception):
            conn.execute("SELECT 1")


# ═══════════════════════════════════════════════════════════════════════════════
# Order CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderCRUD:
    def test_insert_and_query(self, db):
        order = _make_order()
        insert_new_order_to_db(db, username="test_user", order=order)

        rows = db.execute("SELECT order_id, status FROM orders WHERE order_id = ?", (order.id,))
        assert len(rows) == 1
        assert rows[0][0] == order.id
        assert rows[0][1] == "PLACED"

    def test_update_status(self, db):
        order = _make_order()
        insert_new_order_to_db(db, username="u1", order=order)
        update_order_status_to_db(db, order.id, "FILLED")

        rows = db.execute("SELECT status, updated_at FROM orders WHERE order_id = ?", (order.id,))
        assert rows[0][0] == "FILLED"
        assert rows[0][1] is not None  # updated_at should be set

    def test_insert_none_conn_no_crash(self):
        """Passing None conn should just return without error."""
        insert_new_order_to_db(None, username="u", order=_make_order())

    def test_update_none_conn_no_crash(self):
        update_order_status_to_db(None, "fake_id", "FILLED")


# ═══════════════════════════════════════════════════════════════════════════════
# OrderMap CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderMap:
    def test_insert_and_lookup_by_cj_id(self, db):
        insert_new_ordermap_item_to_db(db, "cj_001", "bkr_AAA", "arenax")
        result = get_bkr_order_id_from_db(db, "cj_001")
        assert result == "bkr_AAA"

    def test_lookup_by_broker_id(self, db):
        insert_new_ordermap_item_to_db(db, "cj_002", "bkr_BBB", "sinopac")
        result = get_cj_order_id_from_db(db, "bkr_BBB")
        assert result == "cj_002"

    def test_missing_returns_none(self, db):
        assert get_bkr_order_id_from_db(db, "nonexistent") is None
        assert get_cj_order_id_from_db(db, "nonexistent") is None

    def test_none_conn_returns_none(self):
        assert get_bkr_order_id_from_db(None, "x") is None
        assert get_cj_order_id_from_db(None, "x") is None


# ═══════════════════════════════════════════════════════════════════════════════
# _merge_intervals (pure function)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMergeIntervals:
    def test_empty(self):
        assert _merge_intervals([]) == []

    def test_single(self):
        assert _merge_intervals([(1, 5)]) == [(1, 5)]

    def test_non_overlapping(self):
        assert _merge_intervals([(1, 3), (5, 7)]) == [(1, 3), (5, 7)]

    def test_overlapping(self):
        assert _merge_intervals([(1, 5), (3, 8)]) == [(1, 8)]

    def test_adjacent(self):
        assert _merge_intervals([(1, 5), (6, 10)]) == [(1, 10)]

    def test_unsorted_input(self):
        assert _merge_intervals([(10, 20), (1, 5), (3, 8)]) == [(1, 8), (10, 20)]

    def test_fully_contained(self):
        assert _merge_intervals([(1, 10), (3, 7)]) == [(1, 10)]


# ═══════════════════════════════════════════════════════════════════════════════
# Coverage ranges
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoverageRanges:
    def test_empty_initially(self, price_db):
        ranges = get_coverage_ranges(price_db, "0050")
        assert ranges == []

    def test_upsert_single(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 200, "test")
        ranges = get_coverage_ranges(price_db, "0050")
        assert ranges == [(100, 200)]

    def test_upsert_consolidates_overlapping(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 200, "test")
        upsert_coverage_range(price_db, "0050", "1m", 150, 300, "test")
        ranges = get_coverage_ranges(price_db, "0050")
        assert ranges == [(100, 300)]

    def test_upsert_adjacent(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 200, "test")
        upsert_coverage_range(price_db, "0050", "1m", 201, 300, "test")
        ranges = get_coverage_ranges(price_db, "0050")
        # Adjacent should merge
        assert ranges == [(100, 300)]

    def test_different_symbols_isolated(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 200, "test")
        upsert_coverage_range(price_db, "2330", "1m", 500, 600, "test")
        assert get_coverage_ranges(price_db, "0050") == [(100, 200)]
        assert get_coverage_ranges(price_db, "2330") == [(500, 600)]

    def test_start_gt_end_noop(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 200, 100, "test")
        assert get_coverage_ranges(price_db, "0050") == []


# ═══════════════════════════════════════════════════════════════════════════════
# compute_missing_ranges
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeMissingRanges:
    def test_fully_missing(self, price_db):
        gaps = compute_missing_ranges(price_db, "0050", "1m", 100, 500)
        assert gaps == [(100, 500)]

    def test_fully_covered(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 500, "test")
        gaps = compute_missing_ranges(price_db, "0050", "1m", 100, 500)
        assert gaps == []

    def test_gap_in_middle(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 200, "test")
        upsert_coverage_range(price_db, "0050", "1m", 300, 500, "test")
        gaps = compute_missing_ranges(price_db, "0050", "1m", 100, 500)
        assert gaps == [(201, 299)]

    def test_trailing_gap(self, price_db):
        upsert_coverage_range(price_db, "0050", "1m", 100, 300, "test")
        gaps = compute_missing_ranges(price_db, "0050", "1m", 100, 500)
        assert gaps == [(301, 500)]


# ═══════════════════════════════════════════════════════════════════════════════
# Price insert/query
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriceInsertQuery:
    def test_insert_and_query(self, price_db):
        ts = datetime(2024, 6, 1, 9, 0, 0)
        kbar = Kbar(timestamp=ts, open=50.0, high=52.0, low=49.0, close=51.0, volume=1000)
        ok = insert_price_to_arenax_local_price_db(price_db, "0050", kbar, "1m", "test")
        assert ok is True

        results = get_price_from_arenax_local_price_db(
            price_db, "0050", "1m",
            start_ts=datetime(2024, 6, 1, 0, 0, 0),
            end_ts=datetime(2024, 6, 2, 0, 0, 0),
        )
        assert len(results) == 1
        assert results[0].open == 50.0
        assert results[0].close == 51.0
        assert results[0].volume == 1000

    def test_insert_none_conn_returns_false(self):
        ts = datetime(2024, 1, 1)
        kbar = Kbar(timestamp=ts, open=1.0, high=2.0, low=0.5, close=1.5, volume=10)
        assert insert_price_to_arenax_local_price_db(None, "X", kbar) is False

    def test_insert_none_symbol_returns_false(self, price_db):
        ts = datetime(2024, 1, 1)
        kbar = Kbar(timestamp=ts, open=1.0, high=2.0, low=0.5, close=1.5, volume=10)
        assert insert_price_to_arenax_local_price_db(price_db, None, kbar) is False

    def test_query_empty_result(self, price_db):
        results = get_price_from_arenax_local_price_db(
            price_db, "NONE", "1m",
            start_ts=datetime(2024, 1, 1),
            end_ts=datetime(2024, 12, 31),
        )
        assert results == []

    def test_query_none_conn_returns_empty(self):
        results = get_price_from_arenax_local_price_db(None, "X", "1m")
        assert results == []

    def test_overwrite_mode(self, price_db):
        ts = datetime(2024, 6, 1, 9, 0, 0)
        kbar1 = Kbar(timestamp=ts, open=50.0, high=52.0, low=49.0, close=51.0, volume=1000)
        kbar2 = Kbar(timestamp=ts, open=55.0, high=57.0, low=54.0, close=56.0, volume=2000)

        insert_price_to_arenax_local_price_db(price_db, "0050", kbar1, "1m", "test", overwrite=True)
        insert_price_to_arenax_local_price_db(price_db, "0050", kbar2, "1m", "test", overwrite=True)

        results = get_price_from_arenax_local_price_db(
            price_db, "0050", "1m",
            start_ts=datetime(2024, 6, 1),
            end_ts=datetime(2024, 6, 2),
        )
        assert len(results) == 1
        assert results[0].open == 55.0  # overwritten

    def test_no_overwrite_mode(self, price_db):
        ts = datetime(2024, 6, 1, 9, 0, 0)
        kbar1 = Kbar(timestamp=ts, open=50.0, high=52.0, low=49.0, close=51.0, volume=1000)
        kbar2 = Kbar(timestamp=ts, open=55.0, high=57.0, low=54.0, close=56.0, volume=2000)

        insert_price_to_arenax_local_price_db(price_db, "0050", kbar1, "1m", "test", overwrite=False)
        insert_price_to_arenax_local_price_db(price_db, "0050", kbar2, "1m", "test", overwrite=False)

        results = get_price_from_arenax_local_price_db(
            price_db, "0050", "1m",
            start_ts=datetime(2024, 6, 1),
            end_ts=datetime(2024, 6, 2),
        )
        assert len(results) == 1
        assert results[0].open == 50.0  # first insert preserved


# ═══════════════════════════════════════════════════════════════════════════════
# connect_sqlite
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectSqlite:
    def test_memory_db(self):
        conn = connect_sqlite(":memory:")
        assert conn is not None
        rows = conn.execute("SELECT 42")
        assert rows == [(42,)]
        conn.close()

    def test_file_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = connect_sqlite(db_path)
        assert conn is not None
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        conn.close()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = str(tmp_path / "nested" / "dir" / "test.db")
        conn = connect_sqlite(db_path)
        assert conn is not None
        conn.close()
