from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List

from cjtrade.pkgs.db.db_base import DatabaseConnection

try:
    import duckdb
except ImportError:
    duckdb = None

class DuckDBDatabaseConnection(DatabaseConnection):
    """`DatabaseConnection` backed by duckdb.

    Parameters
    ----------
    connection : Any
        Open duckdb connection.

    Warnings
    --------
    Placeholder, unused: ``execute_script`` is not implemented, so the
    class is still abstract and instantiating it raises TypeError.
    """
    def __init__(self, connection: Any):
        if duckdb is None:
            raise ImportError("duckdb is not installed. Install it with: pip install duckdb")
        super().__init__(connection)

    def close(self) -> None:
        """Close the connection; later calls do nothing."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute(self, command: str) -> Any:
        """Run one statement and return ``cursor.fetchall()``.

        Takes no query parameters, unlike `DatabaseConnection.execute`.

        Raises
        ------
        Exception
            If the connection is closed.
        """
        if not self.connection:
            raise Exception("Database connection is closed.")
        cursor = self.connection.cursor()
        cursor.execute(command)
        return cursor.fetchall()

    def commit(self) -> None:
        """Do nothing; DuckDB auto-commits."""
        # DuckDB auto-commits by default; no action needed
        pass
