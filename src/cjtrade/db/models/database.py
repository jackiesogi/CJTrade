# For simplicity, base class and their children class implementation
# are all in this file. In the future, if the file is too large,
# we can split them into multiple files.
from abc import ABC, abstractmethod
from typing import Any, Dict, List

# database base class
# Current:
#   connect() / disconnect() / is_connected() /
#   execute(str) / commit()
# Future (support parameterized query 參數化查詢):
#   will be implemented in `SqlCommand` class
class Database(ABC):
    def __init__(self, **config: Any):
        self.config = config

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def execute(self, command: str) -> Any:
        pass

    def commit(self) -> None:
        pass


class SqliteDatabase(Database):
    import sqlite3

    def __init__(self, **config: Any):
        super().__init__(**config)
        self.connection = None

    def connect(self) -> bool:
        # specify ":memory:" to use in-memory database
        # specify file path to use file-based database
        self.connection = self.sqlite3.connect(self.config.get("database", ":memory:"))
        return True

    def disconnect(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def is_connected(self) -> bool:
        return self.connection is not None

    def execute(self, command: str) -> Any:
        if not self.is_connected():
            raise Exception("Database is not connected.")
        cursor = self.connection.cursor()
        cursor.execute(command)
        return cursor.fetchall()

    def commit(self) -> None:
        if self.connection:
            self.connection.commit()