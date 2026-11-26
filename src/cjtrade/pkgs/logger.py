"""One logging setup for the whole codebase.

Every module logs through a named logger instead of print():

```python
from cjtrade.pkgs.logger import get_logger

log = get_logger("brokers.sinopac")
log.info("connected (simulation=%s)", simulation)
```

which an app that called :func:`setup_logging` prints as

```text
[INFO][2026-11-25 15:41:29] brokers.sinopac: connected (simulation=False)
```

Naming
------
A logger under ``pkgs/`` is named for its path below ``pkgs/``
(``brokers.sinopac``, ``marketdata.finmind``, ``strategy.adx``). An app's is
named for its path below ``apps/`` (``ArenaX.server``, ``CJShell``), and
the trading engine's start with ``engine``. A tag that used to open a message
(``[Clock]``, ``[Risk]``) is the last part of the name instead, so it is not
repeated in every line. Internally every name sits under ``cjtrade.``, so
``logging.getLogger("cjtrade")`` silences or raises all of them at once; the
prefix is not printed.

Simulated time
--------------
The timestamp in the prefix is the wall clock. Where a message is about a
moment in a replay or a backtest, the simulated time is part of the message,
written ``@2025-09-01 09:05``.

Program output
--------------
What a command prints as its result -- a shell's reply, a report, a table --
is not a log line and must not carry a prefix. It goes through
:func:`get_console`, a logger that writes the bare message to stdout.

Libraries do not configure logging. Only an entry point calls
:func:`setup_logging`; code that imports cjtrade and does not call it gets
Python's default, which shows warnings and errors only.
"""
from __future__ import annotations

import logging
import sys

ROOT = "cjtrade"
CONSOLE = f"{ROOT}.console"

FORMAT = "[%(levelname)s][%(asctime)s] %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that are chatty at INFO/DEBUG and say nothing a user of
# cjtrade needs: urllib3 logs two lines per HTTP call, matplotlib and PIL a
# dozen about fonts whenever a chart is drawn.
NOISY = ("urllib3", "asyncio", "matplotlib", "PIL", "shioaji", "yfinance",
         "peewee", "werkzeug")


def get_logger(name: str) -> logging.Logger:
    """The logger for `name`, e.g. ``"brokers.sinopac"``; see the module docstring."""
    return logging.getLogger(f"{ROOT}.{name}")


class _Stream(logging.StreamHandler):
    """A handler that writes to whatever sys.stdout / sys.stderr is right now.

    A plain StreamHandler keeps the stream it was created with, so output
    would bypass anything that replaces sys.stdout later (pytest's capsys,
    contextlib.redirect_stdout).
    """

    def __init__(self, which: str) -> None:
        super().__init__()
        self._which = which

    @property
    def stream(self):
        return getattr(sys, self._which)

    @stream.setter
    def stream(self, _value) -> None:       # set by StreamHandler.__init__
        pass


class Formatter(logging.Formatter):
    """``[LEVEL][time] name: message``, with the ``cjtrade.`` prefix dropped."""

    def __init__(self) -> None:
        super().__init__(FORMAT, DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if name.startswith(ROOT + "."):
            record = logging.makeLogRecord(record.__dict__)
            record.name = name[len(ROOT) + 1:]
        return super().format(record)


_HANDLER_TAG = "_cjtrade_handler"


def one_line(value) -> str:
    """`value` as text with CR and LF escaped, for logging input from outside.

    A request parameter or anything else a caller controls must not be able to
    start a new log line and forge an entry.
    """
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def kv(values: dict) -> str:
    """``{"a": 1, "t": datetime(...)}`` as ``a=1 t=2025-09-01 09:00:00``, for one log line.

    Shorter than a dict's repr: no quotes, braces or ``datetime.datetime(...)``,
    enums by value. Every key and value is kept.
    """
    from datetime import datetime
    from enum import Enum

    def one(v):
        if isinstance(v, datetime):
            return v.isoformat(sep=" ", timespec="seconds")
        if isinstance(v, Enum):
            return str(v.value)
        return str(v)
    return " ".join(f"{k}={one(v)}" for k, v in values.items())


def setup_logging(level: int | str = logging.INFO, *, quiet: tuple = NOISY) -> None:
    """Send every log line to stderr in the cjtrade format. Call once, from an entry point.

    Parameters
    ----------
    level : int or str
        Level for cjtrade's own loggers, e.g. ``logging.DEBUG`` or ``"DEBUG"``.
        The ``CJTRADE_LOG_LEVEL`` environment variable overrides it.
    quiet : tuple of str
        Third-party loggers held at WARNING.

    Warnings
    --------
    Replaces the root logger's handlers, so anything configured before is
    dropped. Calling it again only changes the level.
    """
    import os
    level = os.environ.get("CJTRADE_LOG_LEVEL", level)
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    root = logging.getLogger()
    if not any(getattr(h, _HANDLER_TAG, False) for h in root.handlers):
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = _Stream("stderr")
        handler.setFormatter(Formatter())
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger(ROOT).setLevel(level)
    for name in quiet:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_console(name: str = "", *, stream: str = "stdout") -> logging.Logger:
    """A logger for program output: the bare message, at INFO and up.

    Use it for what a command prints as its result, never for diagnostics.
    Works whether or not :func:`setup_logging` was called.

    Parameters
    ----------
    name : str
        Child name, e.g. ``"CJShell"``.
    stream : {"stdout", "stderr"}
        ``"stderr"`` is for interactive text from a program whose stdout is
        data, such as a form whose export lines are captured by
        ``eval "$(...)"``. The first call for a name decides its stream.
    """
    if stream == "stderr":
        out = logging.getLogger(f"{CONSOLE}.stderr.{name}" if name else f"{CONSOLE}.stderr")
        if not any(getattr(h, _HANDLER_TAG, False) for h in out.handlers):
            handler = _Stream("stderr")
            handler.setFormatter(logging.Formatter("%(message)s"))
            setattr(handler, _HANDLER_TAG, True)
            out.addHandler(handler)
            out.setLevel(logging.INFO)
            out.propagate = False
        return out
    console = logging.getLogger(CONSOLE)
    if not any(getattr(h, _HANDLER_TAG, False) for h in console.handlers):
        handler = _Stream("stdout")
        handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(handler, _HANDLER_TAG, True)
        console.addHandler(handler)
        console.setLevel(logging.INFO)
        console.propagate = False
    return console.getChild(name) if name else console
