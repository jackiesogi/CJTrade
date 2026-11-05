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


def _default_config_paths() -> List[Path]:
    """Where to look for config, nearest-first.

    The user config directory is searched as well as the CWD so credentials do
    not have to live inside the checkout. load_dotenv(override=False) means the
    FIRST file to set a key wins, so the CWD is listed first and a project-local
    .cjconf still beats the user-level one.

    NOTE: that precedence is the opposite of git's, where the more specific
    scope wins because it is applied last. Reconciling this -- plus recording
    which file each key came from -- is tracked in TODO.md under
    "Config provenance".
    """
    from cjtrade.pkgs import paths

    return [
        Path(".env"),
        Path.cwd(),                 # project-local *.cjconf (recursive)
        paths.config_dir(),         # user-level *.cjconf
    ]


SUPPORTED_CONFIG_PATHS = _default_config_paths()

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
