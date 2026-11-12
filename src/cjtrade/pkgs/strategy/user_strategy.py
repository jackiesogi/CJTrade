"""
pkgs/strategy/user_strategy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Assembles a hand-written strategy module into a BaseStrategy the engine can
drive.

The user writes `on_bar(bar, account)` and returns `buy()` / `sell()` /
`hold()`. Everything between that and the engine happens here: building Bar and
Account, turning an Intent into a Signal with a size, collecting watch/plot
into monitors(), tracking which shares are this bot's, and making sure a
strategy that raises takes down the bar rather than the run.

Nothing in this module is part of the vocabulary a strategy may use -- that is
authoring.py, and keeping the two apart is what lets the editor's completion
list be generated from one module and be exactly right.

Security posture: executing a user's module is running their Python in this
process. FinHub is a single trust domain -- an account on it is permission to
run code on the host -- so this is not a sandbox and does not pretend to be
one. `__builtins__` is left intact, because stripping it stops `len()` and
`range()` without stopping `__import__`, which is the worst of both.
"""
from __future__ import annotations

import ast
import logging
import math
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs.strategy import authoring
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill as EngineFill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)

# A strategy that raises every bar would otherwise write one traceback per
# bar: 22,000 of them in a 120-day replay, which buries everything else in the
# log and still does not say more than the first one did.
MAX_CONSECUTIVE_ERRORS = 5

# The name the module is compiled under. Appears in tracebacks, so it is worth
# being something a user recognises rather than "<string>".
MODULE_NAME = "<strategy>"

# The one import a strategy is expected to write. Named here because the
# static check treats a wildcard from it differently from any other: we know
# exactly what it provides.
AUTHORING_MODULE = "cjtrade.pkgs.strategy.authoring"


class StrategyError(Exception):
    """A strategy's source could not be used.

    `line` and `offset` are 1-based and may be None -- a SyntaxError has them,
    a missing on_bar does not. The editor turns them into a marker.
    """

    def __init__(self, message: str, line: Optional[int] = None,
                 offset: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.offset = offset

    def to_dict(self) -> dict:
        return {"message": self.message, "line": self.line,
                "offset": self.offset}


@dataclass
class Diagnostic:
    """One problem found in a strategy, at a position in the source."""
    message: str
    line: int
    offset: int = 1
    severity: str = "error"          # error | warning

    def to_dict(self) -> dict:
        return {"message": self.message, "line": self.line,
                "offset": self.offset, "severity": self.severity}


# ═══════════════════════════════════════════════════════════════════════════
#  Static checks — what the editor can be told before anything runs
# ═══════════════════════════════════════════════════════════════════════════

# Names a strategy gets for free. Anything else used at module level and never
# assigned is reported, because an undefined name is the one mistake that is
# certain to fail and is invisible until the bar it runs on.
_PROVIDED = frozenset(authoring.__all__) | {
    "on_bar", "on_fill", "on_end", "init",
    "__name__", "__file__", "__doc__", "__builtins__",
}


def check(source: str) -> List[Diagnostic]:
    """Everything that can be known about a strategy without running it.

    Deliberately short of a type checker: a syntax error, a missing on_bar, a
    wrong signature, and the handful of shapes that are always a mistake. The
    editor runs this on every save, so it has to be fast and it has to never
    report a false problem -- a red squiggle on correct code teaches people to
    ignore squiggles.
    """
    try:
        tree = ast.parse(source, filename=MODULE_NAME)
    except SyntaxError as exc:
        return [Diagnostic(exc.msg or "invalid syntax",
                           line=exc.lineno or 1, offset=exc.offset or 1)]

    out: List[Diagnostic] = []
    functions = {node.name: node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    on_bar = functions.get("on_bar")
    if on_bar is None:
        out.append(Diagnostic(
            "a strategy needs a function called on_bar(bar, account)", line=1))
    else:
        if isinstance(on_bar, ast.AsyncFunctionDef):
            out.append(Diagnostic(
                "on_bar must be a plain function, not async -- the engine "
                "calls it inside one bar and cannot await it",
                line=on_bar.lineno))
        got = [a.arg for a in on_bar.args.args]
        if len(got) != 2:
            out.append(Diagnostic(
                f"on_bar takes exactly two arguments, (bar, account); "
                f"this one takes {len(got)}"
                + (f": {', '.join(got)}" if got else ""),
                line=on_bar.lineno))

    for name, expected in (("on_fill", 2), ("on_end", 1), ("init", 0)):
        node = functions.get(name)
        if node is None:
            continue
        got = [a.arg for a in node.args.args]
        if len(got) != expected:
            shape = {"on_fill": "(fill, account)", "on_end": "(account)",
                     "init": "()"}[name]
            out.append(Diagnostic(
                f"{name} takes {expected} argument(s), {shape}; this one "
                f"takes {len(got)}", line=node.lineno))

    out.extend(_undefined_names(tree))
    return out


def _undefined_names(tree: ast.Module) -> List[Diagnostic]:
    """Module-level names that are read but never provided or assigned.

    Only module scope and only names never bound anywhere in the file, which
    keeps it from guessing about comprehensions, walrus bindings, closures or
    anything else where being clever would produce a false positive. It
    catches the case that matters: a typo'd API name, which the completion
    list makes rare and this makes visible when it happens anyway.
    """
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            bound.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                for a in (args.posonlyargs + args.args + args.kwonlyargs):
                    bound.add(a.arg)
                if args.vararg:
                    bound.add(args.vararg.arg)
                if args.kwarg:
                    bound.add(args.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    module = getattr(node, "module", None) or ""
                    if module != AUTHORING_MODULE:
                        # A wildcard from somewhere we do not know the contents
                        # of could provide any name, so every unresolved name
                        # becomes a guess. Give up rather than report one.
                        #
                        # The authoring module is the exception, and it is the
                        # import every strategy is expected to write: its names
                        # are already in _PROVIDED, so checking can continue --
                        # which is the whole point, because a typo'd API name
                        # is the mistake this is here to catch.
                        return []
                    continue
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)

    import builtins
    known = bound | _PROVIDED | set(dir(builtins))

    seen: Dict[str, int] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id not in known and node.id not in seen):
            seen[node.id] = node.lineno

    return [Diagnostic(f"{name} is not defined. It is not part of the "
                       f"strategy API and nothing in this file sets it.",
                       line=line)
            for name, line in sorted(seen.items(), key=lambda kv: kv[1])]


# ═══════════════════════════════════════════════════════════════════════════
#  Loading
# ═══════════════════════════════════════════════════════════════════════════

def _namespace() -> dict:
    """A fresh module namespace with the authoring vocabulary already in it.

    Seeded even though a strategy is expected to write `from ...authoring
    import *`, so that a file without the import still runs. The import line
    is there for the static analysers -- Pyright cannot see names injected
    here, and a file it cannot resolve gets no completion and a red squiggle
    on every call.
    """
    ns: dict = {"__name__": MODULE_NAME, "__doc__": None}
    for name in authoring.__all__:
        ns[name] = getattr(authoring, name)
    return ns


def load(source: str) -> "UserStrategy":
    """Compile and execute a strategy module, and wrap it for the engine.

    Raises StrategyError for anything that makes the source unusable, with a
    line number where one exists. Problems the static check found are raised
    first, because "name is not defined on line 12" is a better answer than
    the NameError the same file produces on bar 1.
    """
    problems = [d for d in check(source) if d.severity == "error"]
    if problems:
        first = problems[0]
        raise StrategyError(first.message, line=first.line, offset=first.offset)

    ns = _namespace()
    try:
        code = compile(source, MODULE_NAME, "exec")
        exec(code, ns)
    except SyntaxError as exc:
        raise StrategyError(exc.msg or "invalid syntax",
                            line=exc.lineno, offset=exc.offset) from exc
    except Exception as exc:
        raise StrategyError(f"the strategy failed while loading: "
                            f"{type(exc).__name__}: {exc}",
                            line=_traceback_line(exc)) from exc

    return UserStrategy(ns)


def collect_params(source: str) -> List[dict]:
    """The parameters a strategy declares, in the order it declares them.

    Works by running the module, because `param.int(100, "Window")` is an
    ordinary call whose side effect is the declaration -- there is no separate
    manifest to keep in step with the code. Running it is acceptable here for
    the same reason it is acceptable at all: single trust domain.
    """
    authoring.param._drain()                 # discard anything left over
    try:
        load(source)
    except StrategyError:
        return []
    return [spec.to_dict() for spec in authoring.param._drain()]


# The cheat sheet every template carries. One copy, because three templates
# with three drifting summaries of the same API is how a reference goes stale.
_CHEAT_SHEET = """What you can use here:
  bar      .close .open .volume .time .closes .ago(n) .bars_seen
           .day_high .day_low  (the DAY's extremes, not this bar's)
  account  .cash .equity .shares .avg_cost .holding
           shares and avg_cost are THIS strategy's, not the whole account's
  ta       .bb .sma .ema .rsi .macd .wma .highest .lowest .efficiency
           each returns the latest value, or None until it has enough bars
  buy()    as much as the risk budget allows.  buy(100) / buy(amount=10000)
  sell()   everything this strategy holds.     sell(50)
  hold("why")   do nothing, and say why — it shows up in the bot's status
  watch(x=...)  numbers to display         plot(x=...)  lines on the chart
  state.x       survives from bar to bar
  param.int/float/bool/choice  tunable, and rendered as a form field"""

TEMPLATE_KINDS = ("bb", "dca", "adx", "blank")


def template(kind: str = "bb", name: str = "My strategy",
             symbol: str = "2317") -> str:
    """A complete, runnable strategy of the asked-for kind.

    These live here rather than in FinHub because they are demonstrations of
    this module's API: if `buy()` grows an argument or `ta` loses an indicator,
    the files that teach it should be the thing that changes with it.

    Each one is a working strategy rather than a skeleton of comments. The
    first thing anyone does is press run, and a file that does nothing teaches
    nothing about what went wrong.

    `bb`, `dca` and `adx` are the same three strategies the engine's built-in
    bot_c, bot_a and bot_b run -- written against this API instead of as
    BaseStrategy subclasses, which is what makes them editable in a browser.
    They are not the same code: a subclass with 200 lines of machinery and a
    25-line on_bar are different artifacts for different readers, and these are
    the ones a person is meant to read.
    """
    if kind not in TEMPLATE_KINDS:
        raise ValueError(f"unknown template {kind!r}; "
                         f"try one of {', '.join(TEMPLATE_KINDS)}")
    title = name.strip() or "My strategy"
    body = _TEMPLATES[kind]
    return body.replace("%TITLE%", title).replace("%SYMBOL%", symbol) \
               .replace("%CHEAT_SHEET%", _CHEAT_SHEET)


# Kept as plain strings with %PLACEHOLDERS% rather than f-strings, so the
# strategy code inside them can use braces freely -- an f-string template
# means doubling every brace in the thing you are teaching.
_BB = '''"""%TITLE% — %SYMBOL%

Bollinger mean reversion. Buy when the price touches the lower band, sell when
it touches the upper, and sit out while the bands are too narrow for the move
to pay for its own costs.

The engine's bot_c runs this strategy.

%CHEAT_SHEET%
"""
from cjtrade.pkgs.strategy.authoring import *

WINDOW = param.int(100, "Bollinger window", min=5, max=500)
MIN_WIDTH = param.float(0.01, "Minimum band width", min=0.0, max=0.5)


def on_bar(bar, account):
    upper, middle, lower = ta.bb(bar.closes, WINDOW)
    if upper is None:
        return hold(f"warming up: {bar.bars_seen} of {WINDOW} bars")

    width = (upper - lower) / middle
    watch(upper=upper, middle=middle, lower=lower, width=width,
          touches=state.touches or 0)
    plot(upper=upper, middle=middle, lower=lower)

    # A squeeze is not worth trading: one tick on a 250 stock is 0.4%, and a
    # round trip costs 0.585% in commission and tax before any slippage.
    if width < MIN_WIDTH:
        return hold(f"squeeze: {width:.3%} under {MIN_WIDTH:.3%}")

    if bar.close <= lower and not account.holding:
        state.touches = (state.touches or 0) + 1
        return buy(reason=f"lower band touch at {bar.close:.2f}")

    if bar.close >= upper and account.holding:
        return sell(reason=f"upper band touch at {bar.close:.2f}")

    return hold(f"price {bar.close:.2f} inside [{lower:.2f}, {upper:.2f}]")
'''

_DCA = '''"""%TITLE% — %SYMBOL%

Monthly dollar-cost averaging. Buy a fixed NT$ amount on the first bar of each
calendar month and never sell, so this is the accumulate-and-hold baseline the
other strategies are measured against.

The engine's bot_a runs this strategy.

Why calendar months and not "every 30 days": 30 days drifts. From 5 January it
pays on 4 February, then 6 March, and 12.2 instalments fit in a year instead of
12. "The first bar of the month" also needs no holiday calendar -- a 1st that
is a weekend or a holiday resolves itself, because the month rolls over on
whatever bar actually arrives.

%CHEAT_SHEET%
"""
from cjtrade.pkgs.strategy.authoring import *

AMOUNT = param.float(10000.0, "NT$ per instalment", min=100.0)


def on_bar(bar, account):
    this_month = (bar.time.year, bar.time.month)

    watch(instalments=state.instalments or 0,
          deployed=state.deployed or 0.0,
          shares=account.shares,
          avg_cost=account.avg_cost,
          amount=AMOUNT)

    if state.last_month == this_month:
        return hold(f"already bought in {bar.time:%Y-%m}")

    # Whole shares of a fixed sum: the remainder is simply not spent. The
    # instalment does not scale with equity, which is the whole point of DCA --
    # it is a property of your income, not of how the portfolio has done.
    shares = int(AMOUNT // bar.close)
    if shares <= 0:
        return hold(f"one share at {bar.close:.2f} costs more than "
                    f"an instalment of {AMOUNT:,.0f}")

    # Marked now, not when it fills. A rejected order loses this month's
    # instalment; marking it on the fill instead would re-signal every bar
    # until one filled and collect a dozen duplicates.
    state.last_month = this_month
    state.instalments = (state.instalments or 0) + 1
    state.deployed = (state.deployed or 0.0) + shares * bar.close

    return buy(shares, reason=f"DCA instalment for {bar.time:%Y-%m}")
'''

_ADX = '''"""%TITLE% — %SYMBOL%

Regime switching. While the price is moving directionally, trade Donchian
breakouts with it; while it is ranging, buy near the bottom of the range and
sell near the top. In between, do nothing.

The engine's bot_b runs this strategy.

What measures the trend is an efficiency ratio -- how much of the path the
price travelled was net displacement -- on a 0-100 scale. A random walk sits
near 100/sqrt(PERIOD), about 27 at the default; a clean trend approaches 100.
It is scale-free, so the thresholds below mean the same thing on a 50 ETF and
a 1,000 semiconductor, and on 1m bars as on daily ones.

This is NOT the Wilder ADX, which needs each bar's own high and low. The feed
samples one price per bar, so bar.day_high and bar.day_low are the trading
day's extremes rather than this bar's, and feeding them to an indicator that
wants bar ranges computes it off a flat line. ta.adx refuses for that reason.

%CHEAT_SHEET%
"""
from cjtrade.pkgs.strategy.authoring import *

PERIOD = param.int(14, "Trend-strength lookback", min=5, max=200)
STRONG = param.float(40.0, "Trending above", min=0.0, max=100.0)
WEAK = param.float(20.0, "Ranging below", min=0.0, max=100.0)
DONCHIAN = param.int(20, "Breakout lookback", min=5, max=200)
EDGE = param.float(0.01, "How near an edge counts", min=0.0, max=0.2)


def on_bar(bar, account):
    strength = ta.efficiency(bar.closes, PERIOD)
    if strength is None:
        return hold(f"warming up: {bar.bars_seen} of {PERIOD + 1} bars")

    # The window must EXCLUDE this bar. Including it makes the high at least
    # this close, so "broke above the high" could never be true.
    earlier = bar.closes[:-1]
    high = ta.highest(earlier, DONCHIAN)
    low = ta.lowest(earlier, DONCHIAN)
    if high is None or low is None or high <= low:
        return hold("no range to trade yet")

    regime = ("trending" if strength > STRONG
              else "ranging" if strength < WEAK else "neutral")
    watch(trend_strength=strength, regime=regime, high=high, low=low)
    plot(high=high, low=low)

    previous = bar.ago(1)
    if previous is None:
        return hold("no previous bar to compare against")

    if regime == "trending":
        # Go with it: a break of the range in a directional market tends to
        # continue, which is the only reason breakouts are worth taking.
        if previous <= high and bar.close > high and not account.holding:
            return buy(reason=f"broke above {high:.2f} while trending "
                              f"(strength {strength:.0f})")
        if previous >= low and bar.close < low and account.holding:
            return sell(reason=f"broke below {low:.2f} while trending")
        return hold(f"trending at {strength:.0f}, price {bar.close:.2f} "
                    f"inside [{low:.2f}, {high:.2f}]")

    if regime == "ranging":
        # Fade it: in a market going nowhere the edges are where it turns.
        near_low = low * (1 + EDGE)
        near_high = high * (1 - EDGE)
        if bar.close <= near_low and not account.holding:
            return buy(reason=f"near the floor {low:.2f} while ranging")
        if bar.close >= near_high and account.holding:
            return sell(reason=f"near the ceiling {high:.2f} while ranging")
        return hold(f"ranging at {strength:.0f}, price {bar.close:.2f} "
                    f"away from both edges")

    return hold(f"neutral at {strength:.0f} — between {WEAK:.0f} and "
                f"{STRONG:.0f}, so neither mode applies")
'''

_BLANK = '''"""%TITLE% — %SYMBOL%

%CHEAT_SHEET%
"""
from cjtrade.pkgs.strategy.authoring import *


def on_bar(bar, account):
    watch(price=bar.close)
    return hold("nothing decided yet")
'''

_TEMPLATES = {"bb": _BB, "dca": _DCA, "adx": _ADX, "blank": _BLANK}


def starter_source(name: str = "My strategy", symbol: str = "2317") -> str:
    """The Bollinger template. Kept as the name the first callers used."""
    return template("bb", name, symbol)


def api_reference() -> List[dict]:
    """Every name a strategy may use, with its signature and its docstring.

    Generated by introspecting authoring.__all__, which is what keeps the
    editor's completion list from drifting away from the code: there is no
    second list to maintain, and a name that is added or removed here changes
    the editor on the next request.
    """
    import inspect

    out: List[dict] = []

    def describe(name: str, obj: Any, kind: str, owner: str = "") -> None:
        try:
            signature = f"{name}{inspect.signature(obj)}"
        except (TypeError, ValueError):
            signature = name
        doc = inspect.getdoc(obj) or ""
        out.append({
            "name": name,
            "qualified": f"{owner}.{name}" if owner else name,
            "kind": kind,
            "signature": signature,
            "doc": doc.strip(),
        })

    for name in authoring.__all__:
        obj = getattr(authoring, name)
        if inspect.isfunction(obj):
            describe(name, obj, "function")
        elif inspect.isclass(obj):
            describe(name, obj, "class")
            for attr, value in vars(obj).items():
                if attr.startswith("_"):
                    continue
                kind = ("property" if isinstance(value, property)
                        else "method" if callable(value) else "field")
                describe(attr, value, kind, owner=name)
            # Dataclass fields are annotations, not class attributes.
            for attr in getattr(obj, "__annotations__", {}):
                if not attr.startswith("_"):
                    out.append({"name": attr, "qualified": f"{name}.{attr}",
                                "kind": "field", "signature": attr, "doc": ""})
        elif inspect.ismodule(obj):
            describe(name, obj, "module")
        else:
            # ta, param, state: instances whose public methods are the API.
            describe(name, obj, "namespace")
            for attr in dir(obj):
                if attr.startswith("_"):
                    continue
                try:
                    value = getattr(obj, attr)
                except AttributeError:
                    continue        # ta.adx and friends refuse on purpose
                describe(attr, value,
                         "method" if callable(value) else "field", owner=name)
    return out


def _traceback_line(exc: BaseException) -> Optional[int]:
    """The line in the strategy where `exc` came from, if any.

    Walks to the innermost frame belonging to the strategy module, so a
    failure inside ta.bb reports the line that called it rather than a line
    number in this repository.
    """
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == MODULE_NAME:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


# ═══════════════════════════════════════════════════════════════════════════
#  The adapter
# ═══════════════════════════════════════════════════════════════════════════

class UserStrategy(BaseStrategy):
    """Drives a hand-written strategy module through the BaseStrategy contract.

    One instance per strategy module. Holds the module's namespace and the
    bookkeeping the module is deliberately not given: how many shares are this
    bot's, what the last bar reported, and how many bars in a row have raised.
    """

    name = "Custom"
    long_name = "Custom strategy"

    def __init__(self, namespace: dict, name: str = "") -> None:
        self._ns = namespace
        self.name = name or "Custom"
        self._on_bar: Callable = namespace["on_bar"]
        self._init: Optional[Callable] = namespace.get("init")
        self._on_fill: Optional[Callable] = namespace.get("on_fill")
        self._on_end: Optional[Callable] = namespace.get("on_end")

        self._sink = authoring._Sink()
        self._max_pct = 0.05
        self._n_bars = 0
        self._n_signals = 0
        self._errors = 0
        self._consecutive_errors = 0
        self._disabled_reason = ""
        # Shares this bot bought and has not sold. Not the account's position:
        # a strategy that sold the account's position would sell shares it
        # never bought. Clamped against what master reports, so it can never
        # ask to sell more than exists.
        self._own_shares = 0
        self._own_cost = 0.0
        # The last value each plotted series took, per bar. The runner reads
        # and clears this; accumulating a series here would grow without bound
        # over a long run and nothing in this process would ever read it.
        self.plotted: Dict[str, float] = {}

    # -- lifecycle --------------------------------------------------------

    def on_start(self, ctx: StrategyContext) -> None:
        self._max_pct = float(ctx.params.get(
            "risk__max_position_pct",
            ctx.params.get("risk_max_position_pct", self._max_pct)))
        authoring.state._reset()
        self._sink = authoring._Sink()
        self._sink.decision = "no bars yet"
        if self._init is None:
            return
        with self._active():
            try:
                self._init()
            except Exception as exc:
                self._note_error("init", exc)

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        self._n_bars += 1
        if self._disabled_reason:
            return []

        closes = ctx.prices(bar.symbol)
        account = self._account(ctx, bar)
        user_bar = authoring.Bar(
            symbol=bar.symbol, time=bar.timestamp, open=float(bar.open),
            close=float(bar.close), volume=int(bar.volume or 0),
            closes=closes, day_high=float(bar.high), day_low=float(bar.low),
        )

        self._sink.plotted = {}
        with self._active():
            try:
                returned = self._on_bar(user_bar, account)
                self._consecutive_errors = 0
            except Exception as exc:
                self._note_error("on_bar", exc)
                return []

        self.plotted = dict(self._sink.plotted)
        return self._to_signals(returned, bar, account)

    def on_fill(self, fill: EngineFill, ctx: StrategyContext) -> None:
        # Before the callback, so a strategy reading account.shares inside
        # on_fill sees the position the fill produced rather than the one
        # before it.
        if fill.action.upper() == "BUY":
            self._own_shares += int(fill.quantity)
            self._own_cost += fill.quantity * fill.price
        else:
            sold = min(self._own_shares, int(fill.quantity))
            if self._own_shares:
                self._own_cost -= self._own_cost * (sold / self._own_shares)
            self._own_shares -= sold
            if self._own_shares <= 0:
                self._own_shares, self._own_cost = 0, 0.0

        if self._on_fill is None or self._disabled_reason:
            return
        with self._active():
            try:
                self._on_fill(
                    authoring.Fill(symbol=fill.symbol, action=fill.action,
                                   quantity=int(fill.quantity),
                                   price=float(fill.price), time=fill.timestamp,
                                   reason=fill.reason),
                    self._account(ctx, None))
            except Exception as exc:
                self._note_error("on_fill", exc)

    def on_end(self, ctx: StrategyContext) -> None:
        if self._on_end is None or self._disabled_reason:
            return
        with self._active():
            try:
                self._on_end(self._account(ctx, None))
            except Exception as exc:
                self._note_error("on_end", exc)

    # -- monitoring -------------------------------------------------------

    def monitors(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "bars_seen": self._n_bars,
            "signals_emitted": self._n_signals,
            "own_shares": self._own_shares,
            "own_avg_cost": (round(self._own_cost / self._own_shares, 2)
                             if self._own_shares else 0.0),
            "last_decision": self._sink.decision,
        }
        if self._errors:
            out["errors"] = self._errors
        if self._disabled_reason:
            out["disabled"] = self._disabled_reason
        # The strategy's own values last, so a name it chose cannot quietly
        # overwrite one of the above and leave the runner reporting a number
        # that means something else.
        for key, value in self._sink.watched.items():
            out[f"w_{key}" if key in out else key] = _wire_safe(value)
        return out

    # -- internals --------------------------------------------------------

    class _Active:
        """Points authoring.watch/plot/hold at this strategy's sink."""

        def __init__(self, sink):
            self._sink = sink

        def __enter__(self):
            authoring._install_sink(self._sink)
            return self._sink

        def __exit__(self, *exc):
            authoring._install_sink(None)
            return False

    def _active(self):
        return self._Active(self._sink)

    def _account(self, ctx: StrategyContext, bar) -> authoring.Account:
        held = ctx.position_qty(bar.symbol) if bar is not None else None
        # Clamped, so `sell()` can never ask for more than the broker holds --
        # the mirror and this counter can disagree after a manual trade or a
        # restart, and the broker's number is the one that can be filled.
        own = self._own_shares if held is None else min(self._own_shares, held)
        return authoring.Account(
            cash=ctx.balance, equity=ctx.equity, shares=own,
            avg_cost=(self._own_cost / self._own_shares
                      if self._own_shares else 0.0),
        )

    def _to_signals(self, returned, bar, account) -> List[Signal]:
        if returned is None:
            return []
        intents = returned if isinstance(returned, (list, tuple)) else [returned]

        out: List[Signal] = []
        for intent in intents:
            if intent is None:
                continue
            if not isinstance(intent, authoring.Intent):
                self._sink.decision = (
                    f"on_bar returned {type(intent).__name__}, which is not a "
                    f"decision — return buy(), sell() or hold()")
                log.warning("[%s] %s", self.name, self._sink.decision)
                continue

            price = float(intent.price if intent.price is not None else bar.close)
            if price <= 0:
                self._sink.decision = f"refusing a {intent.action} at {price}"
                continue

            shares = self._size(intent, price, account)
            if shares <= 0:
                self._sink.decision = (
                    f"{intent.action} wanted but size came out 0"
                    + (f" ({intent.reason})" if intent.reason else ""))
                continue

            self._n_signals += 1
            self._sink.decision = (
                f"{intent.action} {shares} @ {price:.2f}"
                + (f" — {intent.reason}" if intent.reason else ""))
            out.append(Signal(action=intent.action, symbol=bar.symbol,
                              quantity=shares, price=price,
                              reason=intent.reason or f"custom {intent.action}",
                              meta=dict(intent.meta)))
        return out

    def _size(self, intent: authoring.Intent, price: float,
              account: authoring.Account) -> int:
        """Turn an Intent into a share count.

        The three cases are deliberately different: an explicit count is
        obeyed, an amount is divided by the price, and no size at all defers to
        risk policy -- for a BUY the equity fraction the gate allows, for a
        SELL everything this bot holds.
        """
        if intent.shares is not None:
            return max(0, int(intent.shares))
        if intent.amount is not None:
            return int(intent.amount // price)
        if intent.action == "SELL":
            return account.shares
        if account.equity <= 0 or account.cash < price:
            return 0
        return int(account.equity * self._max_pct / price)

    def _note_error(self, where: str, exc: Exception) -> None:
        self._errors += 1
        self._consecutive_errors += 1
        line = _traceback_line(exc)
        detail = (f"{type(exc).__name__}: {exc}"
                  + (f" (line {line})" if line else ""))
        self._sink.decision = f"{where} raised — {detail}"
        log.error("[%s] %s raised on bar %d — %s", self.name, where,
                  self._n_bars, detail)
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self._disabled_reason = (
                f"{where} raised {self._consecutive_errors} bars running; "
                f"last was {detail}")
            log.error("[%s] giving up on this strategy: %s", self.name,
                      self._disabled_reason)


def _wire_safe(value: Any) -> Any:
    """Coerce a watched value into something that survives a wire.

    A strategy watching a numpy scalar, a Decimal or a model object would
    otherwise hand the runner something msgpack cannot encode, and the failure
    would surface as a dead bot rather than a bad value.
    """
    # None survives as None. It is what every indicator returns during
    # warm-up, so turning it into the string "None" would make the commonest
    # watched value in any run unreadable.
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    # numpy scalars and anything else that knows how to be a float.
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return str(value)[:200]
    return round(as_float, 4) if math.isfinite(as_float) else None
