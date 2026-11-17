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
    """Abstract wrapper around a database driver connection.

    Supports both raw SQL (legacy) and parameterized queries.

    Parameters
    ----------
    connection : Any
        Driver connection, kept as ``self.connection``.
    """
    def __init__(self, connection: Any):
        self.connection = connection

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""
        pass

    @abstractmethod
    def execute(self, command: str, params: tuple = None) -> Any:
        """Run one SQL statement and return the fetched rows.

        Parameters
        ----------
        command : str
            SQL statement.
        params : tuple, optional
            Values for the statement's placeholders.
        """
        pass

    @abstractmethod
    def execute_script(self, path: str) -> None:
        """Run a multi-statement SQL script.

        Parameters
        ----------
        path : str
            The script text. Callers pass the file contents, not a path.
        """
        # Execute SQL script from file
        pass

    def commit(self) -> None:
        """Commit the current transaction. Does nothing unless overridden."""
        pass
