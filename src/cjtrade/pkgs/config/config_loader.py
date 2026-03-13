import glob
from pathlib import Path
from typing import Iterable
from typing import List
from typing import Union

from dotenv import load_dotenv

# TODO: Implement a hierarchical configuration structure
# e.g. a setting called "simulation.playback_speed"
class CJTradeConfiguration:
    pass


SUPPORTED_CONFIG_PATHS = [
    Path(".env"),
    Path.cwd(),  # Current working directory
    # Path(".cjtrade_config"),  # Directory with recursive *.cjconf search
]

SUPPORTED_FILE_PATTERN = "*.cjconf"


def load_supported_config_files(
    paths: Iterable[Union[str, Path]] = SUPPORTED_CONFIG_PATHS,
    recursive_pattern: str = SUPPORTED_FILE_PATTERN,
    override: bool = False,
) -> List[str]:
    if paths is None:
        return []

    loaded: List[str] = []

    for entry in paths:
        p = Path(entry)
        entry_str = str(entry)

        # Handle glob patterns
        if any(ch in entry_str for ch in ["*", "?", "["]):
            for match in glob.glob(entry_str, recursive=True):
                match_path = Path(match)
                if match_path.is_file():
                    load_dotenv(str(match_path), override=override)
                    loaded.append(str(match_path))

        # Handle regular files
        elif p.is_file():
            load_dotenv(str(p), override=override)
            loaded.append(str(p))

        # Handle directories (recursive search)
        elif p.is_dir():
            for file_path in p.rglob(recursive_pattern):
                if file_path.is_file():
                    load_dotenv(str(file_path), override=override)
                    loaded.append(str(file_path))

    for l in loaded:
        print(f"Found config file: {l}")
    return loaded
