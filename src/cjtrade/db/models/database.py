# For simplicity, base class and their children class implementation
# are all in this file. In the future, if the file is too large,
# we can split them into multiple files.
from abc import ABC, abstractmethod
from typing import Any, Dict, List
import sqlite3

try:
    import duckdb
except ImportError:
    duckdb = None


# Database connection base class
# Current:
#   close() / execute(str) / commit()
# Future (support parameterized query 參數化查詢):
#   will be implemented in `SqlCommand` class
class DatabaseConnection(ABC):
    def __init__(self, connection: Any):
        self.connection = connection

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def execute(self, command: str) -> Any:
        pass

    def commit(self) -> None:
        pass


class SqliteDatabaseConnection(DatabaseConnection):
    def __init__(self, connection: sqlite3.Connection):
        super().__init__(connection)

    def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute(self, command: str) -> Any:
        if not self.connection:
            raise Exception("Database connection is closed.")
        cursor = self.connection.cursor()
        cursor.execute(command)
        return cursor.fetchall()

    def commit(self) -> None:
        if self.connection:
            self.connection.commit()


class DuckDBDatabaseConnection(DatabaseConnection):
    def __init__(self, connection: Any):
        if duckdb is None:
            raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
        super().__init__(connection)

    def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute(self, command: str) -> Any:
        if not self.connection:
            raise Exception("Database connection is closed.")
        cursor = self.connection.cursor()
        cursor.execute(command)
        return cursor.fetchall()

    def commit(self) -> None:
        # DuckDB auto-commits by default; no action needed
        pass


# Module-level connect functions
def connect_sqlite(database: str = ":memory:") -> SqliteDatabaseConnection:
    conn = sqlite3.connect(database)
    return SqliteDatabaseConnection(conn)


def connect_duckdb(database: str = ":memory:") -> DuckDBDatabaseConnection:
    if duckdb is None:
        raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
    conn = duckdb.connect(database=database)
    return DuckDBDatabaseConnection(conn)