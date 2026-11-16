"""
pkgs/strategy/authoring.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
The whole vocabulary a hand-written strategy may use. Nothing else.

A strategy written against this module is a file like:

    from cjtrade.pkgs.strategy.authoring import *

    WINDOW = param.int(100, "Bollinger window", min=5, max=500)
    MIN_WIDTH = param.float(0.01, "Minimum band width", min=0.0, max=0.5)

    def on_bar(bar, account):
        upper, middle, lower = ta.bb(bar.closes, WINDOW)
        if upper is None:
            return hold("warming up")

        width = (upper - lower) / middle
        watch(upper=upper, middle=middle, lower=lower, width=width)
        plot(upper=upper, middle=middle, lower=lower)

        if width < MIN_WIDTH:
            return hold(f"squeeze: {width:.3%} under {MIN_WIDTH:.3%}")
        if bar.close <= lower and not account.holding:
            return buy(reason="lower band touch")
        if bar.close >= upper and account.holding:
            return sell(reason="upper band touch")
        return hold("price inside the bands")

`init()`, `on_fill(fill, account)` and `on_end(account)` are optional.

Why this is a separate module from pkgs/api/beginner.py
------------------------------------------------------
beginner.py's `buy()` calls `client.buy_stock(...)`: it holds a broker session
and places the order itself. That is right for a human at a REPL and wrong for
a bot, where it would give every bot process its own broker session, put every
order outside the RiskGate, and create a second answer for balance and
positions alongside master's ledger. Same vocabulary, inverted control flow:
here `buy()` returns an *intent* and master's ExecutionEngine decides.

So this module imports no broker client and nothing that opens a socket: no
name in a strategy's namespace, and no attribute of any name in it, reaches a
broker session.

Be precise about what that is worth. It is NOT a sandbox. A strategy is
Python: it can `import os`, and because `cjtrade/__init__.py` imports the shell
the broker client is already in `sys.modules` of any process that loaded this
module, so a determined strategy can reach one in two lines. FinHub is a
single trust domain and an account on it is permission to run code on the
host, which is the only reason that is acceptable. What the narrow namespace
buys is different and still worth having: nobody reaches a broker by accident,
every order goes through master's RiskGate because that is the only path that
exists for the names on offer, and the editor's completion list is exactly the
supported surface rather than everything that happens to be importable.

What this module deliberately does NOT expose, and why
------------------------------------------------------
`ta.adx`, `ta.atr` and `ta.stoch` take (high, low, close) per bar. This feed
cannot provide that: master samples one Snapshot per bar and a Snapshot's high
and low are the trading DAY's so far, not the bar's (main2's _snapshot_real).
Re-exporting them would have every strategy silently computing an indicator
from a flat line -- the exact bug adx.py carried until it was measured. They
raise an explanatory error instead. `bar.day_high` / `bar.day_low` are named
for what they actually are.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence

from cjtrade.pkgs.analytics.technical import ta as _talib

__all__ = [
    # decisions
    "buy", "sell", "hold",
    # observation
    "watch", "plot",
    # persistent values
    "state", "param",
    # indicators
    "ta",
    # types, for annotations and for the editor's completion to describe
    "Bar", "Account", "Fill", "Intent",
    # a couple of things every strategy ends up wanting
    "math", "datetime",
]


# ═══════════════════════════════════════════════════════════════════════════
#  What a strategy is given
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Bar:
    """One closed bar, plus the history behind it.

    `closes` is ordered oldest-first, so `closes[-1] == close` and
    `ta.bb(bar.closes, 20)` reads the way every other Python series does. Pine
    Script indexes the other way round (`close[1]` is the previous bar); use
    `bar.ago(1)` for that, which cannot be confused with `closes[1]`.
    """
    symbol: str
    time: datetime
    open: float
    close: float
    volume: int
    closes: Sequence[float]
    # Named for what the feed actually delivers. These are the trading day's
    # extremes up to this bar, NOT this bar's own -- one sample per bar means
    # a per-bar high and low do not exist to be reported.
    day_high: float
    day_low: float

    def ago(self, n: int) -> Optional[float]:
        """The close `n` bars before this one. `ago(0)` is this bar.

        None rather than an IndexError when the history is not that long yet:
        every strategy's first bars are short, and a crash there is a crash on
        bar 1 of every run.
        """
        if n < 0 or n >= len(self.closes):
            return None
        return float(self.closes[-1 - n])

    @property
    def bars_seen(self) -> int:
        return len(self.closes)


@dataclass(frozen=True)
class Account:
    """What this bot owns and may spend.

    `shares`, `avg_cost` and `holding` describe THIS BOT's position, not the
    whole account's. That distinction is the point: a strategy that sold
    `whatever the account holds` would sell shares another bot bought, or a
    long-term holding seeded into a paper account, and the chain that did so
    had no provenance check anywhere. `cash` and `equity` are the account's,
    because they genuinely are shared.
    """
    cash: float
    equity: float
    shares: int
    avg_cost: float

    @property
    def holding(self) -> bool:
        return self.shares > 0

    @property
    def market_value(self) -> float:
        return self.shares * self.avg_cost


@dataclass(frozen=True)
class Fill:
    """An order of this bot's that executed."""
    symbol: str
    action: str          # BUY | SELL
    quantity: int
    price: float
    time: datetime
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════
#  What a strategy says back
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Intent:
    """A request, not an order. Master's ExecutionEngine decides if and how it
    reaches the broker, and the RiskGate may refuse it outright.

    `shares is None` means "whatever the risk budget allows", which is the
    normal case and the reason position sizing is not a thing a strategy
    computes: the budget is risk policy and it lives with the risk gate.
    """
    action: str                        # BUY | SELL
    shares: Optional[int] = None
    amount: Optional[float] = None     # NT$ to spend, converted at bar close
    price: Optional[float] = None      # limit price; None means the bar's close
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def buy(shares: Optional[int] = None, *, amount: Optional[float] = None,
        price: Optional[float] = None, reason: str = "", **meta) -> Intent:
    """Ask to buy.

    buy()                -> as much as the risk budget allows
    buy(100)             -> exactly 100 shares
    buy(amount=10_000)   -> about NT$10,000 worth, whole shares, rounded down
    buy(price=250.0)     -> limit at 250 instead of the bar's close
    """
    if shares is not None and amount is not None:
        raise ValueError("buy() takes shares or amount, not both")
    return Intent("BUY", shares=shares, amount=amount, price=price,
                  reason=reason, meta=meta)


def sell(shares: Optional[int] = None, *, price: Optional[float] = None,
         reason: str = "", **meta) -> Intent:
    """Ask to sell.

    sell()      -> everything THIS BOT holds (account.shares), not everything
                   the account holds
    sell(50)    -> exactly 50 shares
    """
    return Intent("SELL", shares=shares, price=price, reason=reason, meta=meta)


def hold(reason: str = "") -> None:
    """Do nothing this bar, and say why.

    The reason is not decoration. on_bar declines for several different
    reasons and a caller looking at "no signal" cannot tell them apart, so
    this is what makes a quiet run explainable -- it becomes
    monitors()["last_decision"], which the engine's status API and FinHub both
    show. Returning None without calling hold() is allowed and simply leaves
    the previous reason standing.
    """
    _sink().decision = reason
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Observation
# ═══════════════════════════════════════════════════════════════════════════

def watch(**values: Any) -> None:
    """Name values to be shown alongside this bot's state.

    Call it as often as you like per bar; the last value for a name wins. The
    runner handles everything that makes these safe to put on a wire --
    numpy scalars, rounding, dropping anything that is not a number or a
    string -- so there is no formatting to do here.
    """
    _sink().watched.update(values)


def plot(**series: float) -> None:
    """Name values to be drawn on the price chart, against this bar's time.

    Separate from watch() because the two are consumed differently: a watched
    value is a number to read now, a plotted one is a series accumulated over
    the run. Only numbers can be plotted.
    """
    for key, value in series.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _sink().plotted[key] = float(value)


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent values
# ═══════════════════════════════════════════════════════════════════════════

class _State:
    """Values that survive from one bar to the next.

    Python would make this `global counter` plus a declaration at module
    level; an object avoids the keyword and the two places. Any attribute that
    was never set reads as None rather than raising, because the first bar
    always reads before it writes:

        state.touches = (state.touches or 0) + 1
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return None

    def _reset(self) -> None:
        self.__dict__.clear()

    def __repr__(self) -> str:
        shown = {k: v for k, v in self.__dict__.items()
                 if not k.startswith("_")}
        return f"state({shown})"


state = _State()


# ═══════════════════════════════════════════════════════════════════════════
#  Parameters
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ParamSpec:
    """A declared parameter: its default, and enough to render a form field.

    Collected by reading the module in a declaration pass (see
    user_strategy.collect_params), which is how the editor gets a parameters
    panel without anyone maintaining a second list of what is tunable.
    """
    kind: str                       # int | float | bool | choice
    default: Any
    label: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple = ()

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "default": self.default, "label": self.label}
        if self.minimum is not None:
            out["min"] = self.minimum
        if self.maximum is not None:
            out["max"] = self.maximum
        if self.choices:
            out["choices"] = list(self.choices)
        return out


class _Param:
    """Declares a tunable value and evaluates to its default.

    `WINDOW = param.int(100, "Window")` leaves WINDOW equal to 100, so the
    module is ordinary Python that runs correctly on its own -- the
    declaration is a side effect, not a placeholder that has to be resolved
    before the file means anything.
    """

    def __init__(self) -> None:
        self._declared: Dict[int, ParamSpec] = {}
        self._order: List[ParamSpec] = []
        self._overrides: Dict[str, Any] = {}
        self._next: List[ParamSpec] = []

    # -- declaration ------------------------------------------------------

    def _declare(self, spec: ParamSpec, value: Any) -> Any:
        self._next.append(spec)
        return value

    def int(self, default: int, label: str = "", *, min: Optional[int] = None,
            max: Optional[int] = None) -> int:
        return self._declare(ParamSpec("int", int(default), label or "value",
                                       min, max), int(default))

    def float(self, default: float, label: str = "", *,
              min: Optional[float] = None, max: Optional[float] = None) -> float:
        return self._declare(ParamSpec("float", float(default),
                                       label or "value", min, max),
                             float(default))

    def bool(self, default: bool, label: str = "") -> bool:
        return self._declare(ParamSpec("bool", bool(default), label or "flag"),
                             bool(default))

    def choice(self, default: str, label: str = "", *,
               choices: Sequence[str] = ()) -> str:
        opts = tuple(choices) or (default,)
        if default not in opts:
            raise ValueError(f"default {default!r} is not one of {opts}")
        return self._declare(ParamSpec("choice", default, label or "choice",
                                       choices=opts), default)

    # -- collection, for the runner ---------------------------------------

    def _drain(self) -> List[ParamSpec]:
        out, self._next = self._next, []
        return out


param = _Param()


# ═══════════════════════════════════════════════════════════════════════════
#  Indicators
# ═══════════════════════════════════════════════════════════════════════════

# Takes a single close series. Every one of these is usable on this feed.
_CLOSE_ONLY = ("bb", "ema", "sma", "rsi", "macd", "wma")

# Takes (high, low, close) per bar, which this feed does not have. Listed by
# name so the error can say which, rather than looking like a typo.
_NEEDS_BAR_RANGE = {
    "adx": "ta.adx(high, low, close)",
    "atr": "ta.atr(high, low, close)",
    "stoch": "ta.stoch(high, low, close)",
}


class _Indicators:
    """The indicators that are honest on a one-sample-per-bar feed.

    Each returns the LATEST value rather than the whole array, and None while
    there is not enough history. That removes the two lines every strategy
    would otherwise open with -- a length check and a `[-1]` -- and it removes
    the commonest mistake, which is forgetting the length check and reading
    nan.
    """

    @staticmethod
    def _latest(arrays, want: int):
        """Last element of each returned array, or None if it is not finite."""
        out = []
        for arr in arrays:
            if arr is None or len(arr) == 0:
                return None if want == 1 else (None,) * want
            value = float(arr[-1])
            if not math.isfinite(value):
                return None if want == 1 else (None,) * want
            out.append(value)
        return out[0] if want == 1 else tuple(out)

    def bb(self, closes: Sequence[float], timeperiod: int = 20,
           nbdevup: float = 2, nbdevdn: float = 2):
        """Bollinger bands. Returns (upper, middle, lower), or (None, None,
        None) until `timeperiod` bars have been seen."""
        if len(closes) < timeperiod:
            return (None, None, None)
        arrays = _talib.bb(_as_array(closes, timeperiod), timeperiod=timeperiod,
                           nbdevup=nbdevup, nbdevdn=nbdevdn)
        return self._latest(arrays, 3)

    def sma(self, closes: Sequence[float], timeperiod: int = 20):
        """Simple moving average, or None until there is enough history."""
        if len(closes) < timeperiod:
            return None
        return self._latest([_talib.sma(_as_array(closes, timeperiod),
                                        timeperiod=timeperiod)], 1)

    def ema(self, closes: Sequence[float], timeperiod: int = 20):
        """Exponential moving average, or None until there is enough history.

        Unlike an SMA an EMA depends on every bar before it, so this is fed
        the whole series rather than the last `timeperiod` values.
        """
        if len(closes) < timeperiod:
            return None
        return self._latest([_talib.ema(_as_array(closes), timeperiod=timeperiod)], 1)

    def rsi(self, closes: Sequence[float], timeperiod: int = 14):
        """Relative strength index 0-100, or None until there is enough history."""
        if len(closes) < timeperiod + 1:
            return None
        return self._latest([_talib.rsi(_as_array(closes), timeperiod=timeperiod)], 1)

    def macd(self, closes: Sequence[float], fastperiod: int = 12,
             slowperiod: int = 26, signalperiod: int = 9):
        """Returns (macd, signal, histogram), or (None, None, None) while short."""
        need = slowperiod + signalperiod
        if len(closes) < need:
            return (None, None, None)
        arrays = _talib.macd(_as_array(closes), fastperiod=fastperiod,
                             slowperiod=slowperiod, signalperiod=signalperiod)
        return self._latest(arrays, 3)

    def wma(self, closes: Sequence[float], timeperiod: int = 20):
        """Weighted moving average, or None until there is enough history."""
        if len(closes) < timeperiod:
            return None
        return self._latest([_talib.wma(_as_array(closes, timeperiod),
                                        timeperiod=timeperiod)], 1)

    # ------------------------------------------------------------------

    def highest(self, closes: Sequence[float], lookback: int):
        """Highest close over the last `lookback` bars (a Donchian top)."""
        if not len(closes):
            return None
        return float(max(closes[-lookback:]))

    def lowest(self, closes: Sequence[float], lookback: int):
        """Lowest close over the last `lookback` bars (a Donchian bottom)."""
        if not len(closes):
            return None
        return float(min(closes[-lookback:]))

    def efficiency(self, closes: Sequence[float], lookback: int = 14):
        """Trend strength 0-100: how much of the path was net directional.

        Scale-free, so the same number means the same thing on any symbol and
        any bar length. A random walk sits near 100/sqrt(lookback); a clean
        trend approaches 100. This is what adx.py uses, because a real ADX
        needs a per-bar high and low that this feed does not carry.
        """
        if len(closes) < lookback + 1:
            return None
        window = list(closes[-lookback:])
        path = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
        if path <= 0:
            return 0.0
        return min(100.0, abs(window[-1] - window[0]) / path * 100.0)

    def __getattr__(self, name: str):
        if name in _NEEDS_BAR_RANGE:
            raise AttributeError(
                f"ta.{name} is not available to a strategy on this feed. "
                f"{_NEEDS_BAR_RANGE[name]} needs each bar's own high and low, "
                f"and the engine samples one price per bar -- bar.day_high and "
                f"bar.day_low are the trading day's extremes, not this bar's, "
                f"so feeding them in would compute the indicator off a flat "
                f"line. For trend strength use ta.efficiency(bar.closes).")
        raise AttributeError(
            f"ta.{name} does not exist. Available: "
            + ", ".join(sorted(_CLOSE_ONLY + ("highest", "lowest", "efficiency"))))


def _as_array(closes: Sequence[float], tail: Optional[int] = None):
    """TA-Lib wants a float array. Slice first when the indicator only needs
    the tail, so the allocation does not grow with the whole run."""
    import numpy as np
    data = closes[-tail:] if tail else closes
    return np.asarray(data, dtype=float)


ta = _Indicators()


# ═══════════════════════════════════════════════════════════════════════════
#  Where watch/plot/hold write
# ═══════════════════════════════════════════════════════════════════════════

class _Sink:
    """Collects what the current bar reported.

    A module global rather than something threaded through every call, because
    one bot is one process is one strategy -- bot_runner.run_bot takes a single
    strategy and never runs two. If that ever stops being true this has to
    become a contextvar, and the symptom would be two strategies overwriting
    each other's `watch` values.
    """

    def __init__(self) -> None:
        self.watched: Dict[str, Any] = {}
        self.plotted: Dict[str, float] = {}
        self.decision: str = "not started"


_ACTIVE: Optional[_Sink] = None


def _sink() -> _Sink:
    """The live sink, or a throwaway one.

    A throwaway rather than an error so that a strategy module can be imported
    and its functions called directly -- in a test, in a notebook, or by a
    user who just runs the file -- without the bookkeeping being set up.
    """
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = _Sink()
    return _ACTIVE


def _install_sink(sink: Optional[_Sink]) -> None:
    """Point watch/plot/hold at `sink`. Called only by the runner."""
    global _ACTIVE
    _ACTIVE = sink
