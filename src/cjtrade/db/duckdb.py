from abc import ABC, abstractmethod
from typing import Any, Dict, List

from cjtrade.db.db_base import DatabaseConnection

try:
    import duckdb
except ImportError:
    duckdb = None

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

