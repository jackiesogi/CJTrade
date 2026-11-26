"""CJTrade: a Taiwan-stock trading framework with a simulated broker."""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    # One source for the version: pyproject.toml, as installed.
    __version__ = _version("cjtrade")
except PackageNotFoundError:        # imported from a source tree, not installed
    __version__ = "0+unknown"


def cli():
    """The ``cjtrade`` command: the interactive shell.

    Imported here rather than at the top, so ``import cjtrade.pkgs...`` does
    not load the shell and everything it depends on.
    """
    from cjtrade.apps.cjtrade_shell import cjtrade_shell
    cjtrade_shell.main()
