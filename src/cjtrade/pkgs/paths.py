"""Where CJTrade keeps user data, config, cache, state and logs.

Single source of truth for every path that is not source code. Importing this
instead of writing a literal keeps three things true:

1. It is cross-platform. Hard-coding "./data/..." puts user data inside
   whatever directory the process happened to start in -- usually the repo, so
   a trading account's mirror DB ends up next to the code that reads it, and a
   `git clean` can delete it. Hard-coding "~/.config/..." is wrong on macOS and
   Windows, which do not use XDG.

2. It is relocatable. CJTRADE_HOME overrides everything, which is how you run
   two independent instances (say a paper and a backtest one) without them
   sharing a price cache or an account state.

3. The categories mean something. platformdirs separates data (keep), cache
   (safe to delete, will be refetched), state (machine-local, survives reboot)
   and logs. Putting a 160MB refetchable price cache under "data" is why
   backups and `du` get confusing.

Typical locations
-----------------
    macOS    ~/Library/Application Support/cjtrade
             ~/Library/Caches/cjtrade
    Linux    ~/.local/share/cjtrade        (XDG_DATA_HOME)
             ~/.cache/cjtrade              (XDG_CACHE_HOME)
    Windows  %LOCALAPPDATA%\\cjtrade

Override with CJTRADE_HOME=/some/path, which puts every category under it as
data/, config/, cache/, state/ and logs/ -- handy for tests and for keeping a
run entirely self-contained.
"""
from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP_NAME = "cjtrade"

# appauthor=False keeps Windows from inserting an author directory, so the
# layout is <root>/cjtrade on every platform rather than <root>/Author/cjtrade.
_DIRS = platformdirs.PlatformDirs(appname=APP_NAME, appauthor=False)

_HOME_ENV = "CJTRADE_HOME"


def _root_override() -> Path | None:
    """CJTRADE_HOME, if set, else None."""
    raw = os.environ.get(_HOME_ENV)
    return Path(raw).expanduser() if raw else None


def _resolve(category: str, platform_default: str, *, ensure: bool) -> Path:
    override = _root_override()
    path = (override / category) if override else Path(platform_default)
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir(*, ensure: bool = True) -> Path:
    """Durable user data: account states, mirror DBs. Losing this loses history."""
    return _resolve("data", _DIRS.user_data_dir, ensure=ensure)


def config_dir(*, ensure: bool = True) -> Path:
    """User config: .cjconf files and anything else the user edits by hand."""
    return _resolve("config", _DIRS.user_config_dir, ensure=ensure)


def cache_dir(*, ensure: bool = True) -> Path:
    """Refetchable data: the ArenaX price cache. Safe to delete at any time."""
    return _resolve("cache", _DIRS.user_cache_dir, ensure=ensure)


def state_dir(*, ensure: bool = True) -> Path:
    """Machine-local state that is not user-authored: saved form answers."""
    return _resolve("state", _DIRS.user_state_dir, ensure=ensure)


def log_dir(*, ensure: bool = True) -> Path:
    """Log files."""
    return _resolve("logs", _DIRS.user_log_dir, ensure=ensure)


# ── Named locations ───────────────────────────────────────────────────────────
# Defined here rather than at each call site so a filename appears exactly once.

def price_db_path() -> Path:
    """ArenaX historical price cache. Cache, not data: it is refetchable."""
    return cache_dir() / "arenax_price.db"


def mirror_db_path(broker: str, username: str = "") -> Path:
    """Local mirror of a broker's orders and fills.

    Data, not cache: CJ_OrderMap here is the only link between a CJTrade order
    id and the broker's own id, so losing it orphans live orders.
    """
    stem = f"{broker}_{username}" if username else broker
    return data_dir() / "mirrors" / f"{stem}.db"


def account_states_dir() -> Path:
    """Per-session account snapshots, one immutable uuid-named file each."""
    d = data_dir() / "account_states"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir() -> Path:
    """Backtest reports: HTML tearsheets and pickled BacktestResults.

    Data, not cache: a report describes one run of a strategy against one
    account state, and neither can be reconstructed once the account has moved
    on -- so unlike the price cache, deleting this loses something.
    """
    d = data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def form_state_dir() -> Path:
    """Remembered answers for pkgs.ui forms, keyed by schema stem."""
    d = state_dir() / "form_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path(name: str) -> Path:
    """A named log file, e.g. log_path("cjtrade_system.log")."""
    return log_dir() / name


def describe() -> str:
    """Human-readable summary of every location, for diagnostics.

    `cjtrade` subcommands print this so a user reporting a problem can say
    where their data actually lives instead of guessing.
    """
    override = _root_override()
    lines = [
        f"CJTRADE_HOME : {override if override else '(unset — using platform defaults)'}",
        f"data         : {data_dir(ensure=False)}",
        f"config       : {config_dir(ensure=False)}",
        f"cache        : {cache_dir(ensure=False)}",
        f"state        : {state_dir(ensure=False)}",
        f"logs         : {log_dir(ensure=False)}",
        f"reports      : {data_dir(ensure=False) / 'reports'}",
    ]
    return "\n".join(lines)


# ── Legacy layout ─────────────────────────────────────────────────────────────

LEGACY_DATA_DIR = Path("data")


def legacy_data_warning() -> str | None:
    """Warn when the pre-platformdirs ./data directory still holds files.

    Deliberately does not move anything: the price cache runs into the hundreds
    of megabytes and has live -shm/-wal sidecars, so relocating it underneath a
    running process is a good way to corrupt it. Tell the user the command
    instead and let them pick the moment.
    """
    if not LEGACY_DATA_DIR.is_dir():
        return None
    leftovers = [p for p in LEGACY_DATA_DIR.iterdir() if p.name != ".gitkeep"]
    if not leftovers:
        return None
    return (
        f"Found {len(leftovers)} file(s) in the legacy ./data directory, which is "
        f"no longer read. To keep your price cache and account history:\n"
        f"    mv data/arenax_price.db* {cache_dir(ensure=False)}/\n"
        f"    mv data/account_states   {data_dir(ensure=False)}/\n"
        f"    mkdir -p {data_dir(ensure=False)}/mirrors && mv data/*.db "
        f"{data_dir(ensure=False)}/mirrors/\n"
        f"Otherwise ./data can be deleted; the cache will be refetched."
    )
