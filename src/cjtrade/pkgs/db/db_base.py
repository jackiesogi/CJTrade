# For simplicity, base class and their children class implementation
# are all in this file. In the future, if the file is too large,
# we can split them into multiple files.
from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List


# Database connection base class
# Supports both raw SQL (legacy) and parameterized queries.
class DatabaseConnection(ABC):
    def __init__(self, connection: Any):
        self.connection = connection

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def execute(self, command: str, params: tuple = None) -> Any:
        pass

    @abstractmethod
    def execute_script(self, path: str) -> None:
        # Execute SQL script from file
        pass

    def commit(self) -> None:
        pass
