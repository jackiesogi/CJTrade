import sqlite3
from typing import Any

from cjtrade.pkgs.db.db_base import DatabaseConnection

# TODO: execute / query_one / query_all
class SqliteDatabaseConnection(DatabaseConnection):
    """`DatabaseConnection` backed by `sqlite3`.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open connection, usually from `connect_sqlite`.
    """
    def __init__(self, connection: sqlite3.Connection):
        super().__init__(connection)

    def close(self) -> None:
        """Close the connection; later calls do nothing."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute(self, command: str, params: tuple = None) -> Any:
        """Run one statement and return ``cursor.fetchall()``.

        Parameters
        ----------
        command : str
            SQL statement.
        params : tuple, optional
            Values for ``?`` placeholders.

        Returns
        -------
        list of tuple
            Fetched rows; empty for statements that return none.

        Raises
        ------
        Exception
            If the connection is closed.
        """
        if not self.connection:
            raise Exception("Database connection is closed.")
        cursor = self.connection.cursor()
        if params is not None:
            cursor.execute(command, params)
        else:
            cursor.execute(command)
        return cursor.fetchall()

    def execute_script(self, path):
        """Run a multi-statement SQL script with ``executescript``.

        Parameters
        ----------
        path : str
            The script text, not a file path.

        Returns
        -------
        list
            ``cursor.fetchall()`` after the script.

        Warnings
        --------
        ``sqlite3`` commits any pending transaction before running the script.
        """
        cursor = self.connection.cursor()
        cursor.executescript(path)
        return cursor.fetchall()

    def commit(self) -> None:
        """Commit the current transaction if the connection is open."""
        if self.connection:
            self.connection.commit()
