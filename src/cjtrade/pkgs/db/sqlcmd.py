from typing import Any
from typing import Dict
from typing import List

# For supporting parameterized query
class SqlCommand():
    def __init__(self, sql_command: str, db_connection: Database):
        self.command = sql_command
        self.db_connection = db_connection
        self.parameters: Dict[str, Any] = {}
        for key in self._extract_params():
            self.parameters[key] = None

    # param is the word starts with @
    def _extract_params(self) -> List[str]:
        params = []
        for word in self.command.split():
            if word.startswith("@"):
                params.append(word[1:])
        return params

    def add_param_with_value(self, key: str, value: Any) -> None:
        if key in self.parameters:
            self.parameters[key] = value
        else:
            raise KeyError(f"Parameter {key} not found in command.")

    def execute_reader(self):
        res = self.db_connection.execute(self.command)
        return res
