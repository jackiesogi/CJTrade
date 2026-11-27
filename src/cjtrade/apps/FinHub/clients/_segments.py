"""Check request values before they become part of an upstream URL.

The engine and the broker are on loopback, but a symbol, an order id or a bot
id still comes from the browser. Left unchecked, ``../`` or ``?`` in one would
change which upstream route FinHub calls, or add a query to it.
"""
import re

SYMBOL = re.compile(r"[0-9]{4,6}[A-Z]?")       # 2330, 00632R
ORDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")   # uuid4().hex and the broker's ids
BOT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")     # Bot_B, Bot_U1


class BadSegment(ValueError):
    """A value that cannot be used in an upstream path."""


def segment(value: str, pattern: re.Pattern, what: str) -> str:
    """`value` if it matches `pattern` completely, else BadSegment."""
    text = str(value)
    if not pattern.fullmatch(text):
        raise BadSegment(f"invalid {what}: {text[:40]!r}")
    return text
