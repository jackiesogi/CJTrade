"""CJTrade: a Taiwan-stock trading framework with a simulated broker."""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    # One source for the version: pyproject.toml, as installed.
    __version__ = _version("cjtrade")
except PackageNotFoundError:        # imported from a source tree, not installed
    __version__ = "0+unknown"
