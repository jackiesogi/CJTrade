import sqlite3
from typing import Any

from cjtrade.db.db_base import DatabaseConnection

# TODO: execute / query_one / query_all
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

    def execute_script(self, path):
        cursor = self.connection.cursor()
        cursor.executescript(path)
        return cursor.fetchall()

    def commit(self) -> None:
        if self.connection:
            self.connection.commit()
