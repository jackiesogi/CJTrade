"""Loading of ``.cjconf`` configuration files.

ONE RULE
--------
**The first source to set a key wins.** Later sources cannot overwrite it.
That is ``load_dotenv(override=False)``, and it applies uniformly to every
source below.

So the search order *is* the precedence order, most specific first:

    0. environment variables already set     (set before we run, so nothing
                                              in a file can displace them)
    1. ./.env
    2. ./**/*.cjconf                         shallower before deeper,
                                             alphabetical within a depth
    3. <user config dir>/*.cjconf            see pkgs.paths.config_dir()

Bundled ``*.cjsys`` defaults are *not* loaded here. Apps load them separately
(``brokerside_server.load_cjsys``) after calling this, which under the
first-wins rule makes package defaults the weakest source of all -- correct for
defaults, but worth knowing when a ``.cjsys`` value appears to be ignored.

Differences from git, deliberately kept for now
-----------------------------------------------
``git config`` applies the least specific scope first and lets later ones
overwrite, so the most specific wins by being applied last. Here the most
specific wins by being applied *first*. The resolved value usually agrees, but
the mechanism is inverted, and flipping it would silently change what every
existing deployment resolves to. Tracked in TODO.md under "Config provenance",
together with recording which file each key came from.

Within a directory the order used to be whatever ``rglob`` returned, i.e. the
filesystem's ``readdir`` order -- so two ``.cjconf`` files setting the same key
resolved differently on different machines. ``_discover`` now sorts by depth
then path, which is deterministic and matches git's local-beats-parent
intuition.
"""
import glob
from pathlib import Path
from typing import List
from typing import Union

from dotenv import load_dotenv

# TODO: Implement a hierarchical configuration structure
# e.g. a setting called "simulation.playback_speed"
# See TODO.md "Config provenance" — hierarchical keys and provenance are two
# sides of the same change.
class CJTradeConfiguration:
    pass


SUPPORTED_FILE_PATTERN = "*.cjconf"

# Distinguishes "argument not given" (use the defaults) from an explicit None,
# which has always meant "load nothing" and is relied on by callers and tests.
# A plain None default would conflate the two.
_UNSET = object()


def default_config_paths() -> List[Path]:
    """Search roots, most specific first. Resolved lazily.

    Not a module-level constant: ``paths.config_dir()`` creates the directory,
    and evaluating this at import time would create it just by importing.
    """
    from cjtrade.pkgs import paths

    return [
        Path(".env"),
        Path.cwd(),                 # project-local *.cjconf, searched recursively
        paths.config_dir(),         # user-level *.cjconf
    ]


def _sort_key(path: Path) -> tuple:
    """Shallower first, then alphabetical.

    Keeps a tree with several ``.cjconf`` files resolving the same way on every
    machine, and gives ./x.cjconf precedence over ./sub/x.cjconf under the
    first-wins rule -- the same shape as git preferring a nearer config.
    """
    parts = path.parts
    return (len(parts), parts)


def _discover(entry: Union[str, Path], pattern: str) -> List[Path]:
    """Expand one search root into an ordered list of files to load."""
    entry_str = str(entry)
    p = Path(entry)

    if any(ch in entry_str for ch in "*?["):
        found = [Path(m) for m in glob.glob(entry_str, recursive=True)]
        return sorted((f for f in found if f.is_file()), key=_sort_key)

    if p.is_file():
        return [p]

    if p.is_dir():
        return sorted((f for f in p.rglob(pattern) if f.is_file()), key=_sort_key)

    return []


def config_sources(
    paths_=_UNSET,
    recursive_pattern: str = SUPPORTED_FILE_PATTERN,
) -> List[Path]:
    """The files that would be loaded, in precedence order. Loads nothing.

    Useful on its own for answering "which files is this process reading?", and
    it is the ordering the provenance work in TODO.md will attach sources to.

    Pass None to mean "no sources at all"; omit the argument for the defaults.
    """
    if paths_ is None:
        return []
    roots = default_config_paths() if paths_ is _UNSET else list(paths_)
    ordered: List[Path] = []
    seen = set()
    for entry in roots:
        for f in _discover(entry, recursive_pattern):
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                ordered.append(f)
    return ordered


def load_supported_config_files(
    paths=_UNSET,
    recursive_pattern: str = SUPPORTED_FILE_PATTERN,
    override: bool = False,
) -> List[str]:
    """Load every discovered config file into ``os.environ``.

    Args:
        paths: Search roots, most specific first. Omit for
            ``default_config_paths()``; pass None to load nothing.
        recursive_pattern: Glob applied when a root is a directory.
        override: Leave at False to keep the first-wins rule. Passing True
            inverts the precedence of every source at once, so do it knowingly.

    Returns:
        The loaded file paths as strings, in the order they were applied.
    """
    loaded: List[str] = []
    for f in config_sources(paths, recursive_pattern):
        load_dotenv(str(f), override=override)
        loaded.append(str(f))

    for l in loaded:
        print(f"Found config file: {l}")
    return loaded


def describe_sources(
    paths=_UNSET,
    recursive_pattern: str = SUPPORTED_FILE_PATTERN,
) -> str:
    """Human-readable listing of the search order, for diagnostics."""
    files = config_sources(paths, recursive_pattern)
    if not files:
        return "No config files found."
    lines = ["Config files, in precedence order (first to set a key wins):"]
    lines += [f"  {i}. {f}" for i, f in enumerate(files, 1)]
    return "\n".join(lines)
