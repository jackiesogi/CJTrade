"""The strategy-authoring surface, and the adapter that drives it.

A strategy written in FinHub's editor is a module with `on_bar(bar, account)`
in it, written against pkgs/strategy/authoring.py and executed by
pkgs/strategy/user_strategy.py. Two things are being protected here:

* The *contract*, because it is the one API in this repository that people
  outside it write against. A rename is a breaking change for every strategy
  anybody has saved.
* The *containment*, because a hand-written strategy is the least trustworthy
  code in the system. It must not be able to place an order, it must not be
  able to sell shares it did not buy, and when it raises it must take down the
  bar rather than the run.

Not a security boundary: FinHub is a single trust domain and a strategy is
Python that can `import os`. What is tested is that nothing goes wrong by
accident and that the supported surface is exactly what it claims.
"""
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.strategy import authoring
from cjtrade.pkgs.strategy import user_strategy as us
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

SYM = "2317"
T0 = datetime(2026, 1, 5, 9, 1)
PREAMBLE = "from cjtrade.pkgs.strategy.authoring import *\n"


def _ctx(prices, *, qty=0, equity=100_000.0, cash=100_000.0, params=None,
         at=None) -> StrategyContext:
    positions = []
    if qty:
        positions = [{"symbol": SYM, "quantity": qty, "avg_cost": 100.0,
                      "current_price": prices[-1] if prices else 100.0,
                      "market_value": qty * 100.0, "unrealized_pnl": 0.0}]
    return StrategyContext(
        timestamp=at or T0, balance=cash, equity=equity, positions=positions,
        price_history={SYM: list(prices)}, bar_index=len(prices),
        params=params if params is not None
        else {"risk__max_position_pct": 0.20})


def _bar(close, i=0, symbol=SYM) -> Kbar:
    return Kbar(symbol=symbol, timestamp=T0 + timedelta(minutes=i),
                open=close, high=close, low=close, close=close, volume=10)


def _loaded(body: str) -> us.UserStrategy:
    """Load `body` with the import line every strategy is expected to have."""
    strategy = us.load(PREAMBLE + body)
    strategy.on_start(_ctx([]))
    return strategy


def _drive(strategy, closes, *, qty=0):
    """Feed closes one bar at a time; return every signal with its bar index."""
    out, prices = [], []
    for i, close in enumerate(closes):
        prices.append(close)
        for sig in strategy.on_bar(_bar(close, i), _ctx(prices, qty=qty)) or []:
            out.append((i, sig.action, sig.quantity, sig.price, sig.reason))
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  The static check — what the editor can say before anything runs
# ═══════════════════════════════════════════════════════════════════════════

class TestCheck:

    def test_the_starter_template_is_clean(self):
        """Whatever else changes, the file handed to a new user must pass."""
        assert us.check(us.starter_source("Fade the band", "2330")) == []

    def test_a_syntax_error_keeps_python_own_wording(self):
        got = us.check("def on_bar(bar, account)\n    pass\n")
        assert [d.line for d in got] == [1]
        assert "expected" in got[0].message        # "expected ':'"

    def test_a_missing_on_bar_is_reported(self):
        assert any("called on_bar" in d.message for d in us.check("x = 1\n"))

    @pytest.mark.parametrize("header,count", [
        ("def on_bar(bar):", 1),
        ("def on_bar():", 0),
        ("def on_bar(bar, account, extra):", 3),
    ])
    def test_the_wrong_arity_is_reported_with_the_count(self, header, count):
        got = us.check(f"{header}\n    pass\n")
        assert any(f"takes {count}" in d.message for d in got), got

    def test_an_async_on_bar_is_reported(self):
        got = us.check("async def on_bar(bar, account):\n    return None\n")
        assert any("not async" in d.message for d in got), got

    @pytest.mark.parametrize("name,shape", [
        ("on_fill", "(fill, account)"), ("on_end", "(account)"), ("init", "()"),
    ])
    def test_the_optional_hooks_are_checked_too(self, name, shape):
        src = (f"{PREAMBLE}def on_bar(bar, account):\n    return hold()\n"
               f"def {name}(a, b, c):\n    pass\n")
        assert any(shape in d.message for d in us.check(src)), us.check(src)

    def test_a_typo_in_an_api_name_is_caught_through_the_wildcard_import(self):
        """The import every strategy writes is `from ...authoring import *`.
        A checker that gave up on wildcards would therefore never catch the
        one mistake it exists for, so this import is the known exception."""
        got = us.check(f"{PREAMBLE}def on_bar(bar, account):\n"
                       f"    return buyy()\n")
        assert [(d.line, "buyy" in d.message) for d in got] == [(3, True)]

    def test_a_wildcard_from_anywhere_else_stops_the_guessing(self):
        """Any name could come from there, so every unresolved name would be a
        guess, and a red squiggle on correct code teaches people to ignore
        squiggles."""
        got = us.check(f"from os.path import *\n{PREAMBLE}"
                       f"def on_bar(bar, account):\n    return mystery()\n")
        assert got == []

    @pytest.mark.parametrize("body", [
        "def on_bar(bar, account):\n    total = 0\n    return hold(str(total))\n",
        "def on_bar(bar, account):\n    return hold(str([x for x in range(3)]))\n",
        "def on_bar(bar, account):\n"
        "    try:\n        pass\n    except ValueError as exc:\n"
        "        return hold(str(exc))\n    return hold()\n",
        "import math\ndef on_bar(bar, account):\n    return hold(str(math.pi))\n",
        "def helper(n):\n    return n\n"
        "def on_bar(bar, account):\n    return hold(str(helper(1)))\n",
    ])
    def test_no_false_positives_on_ordinary_python(self, body):
        assert us.check(PREAMBLE + body) == []

    def test_builtins_are_not_reported(self):
        assert us.check(f"{PREAMBLE}def on_bar(bar, account):\n"
                        f"    return hold(str(len(bar.closes)))\n") == []


class TestLoad:

    @pytest.mark.parametrize("src,needle", [
        ("def on_bar(bar):\n    pass\n", "two arguments"),
        ("def on_bar(bar, account)\n", "expected"),
        ("1 / 0\ndef on_bar(bar, account):\n    return None\n", "while loading"),
    ])
    def test_a_bad_source_raises_rather_than_failing_on_bar_one(self, src,
                                                                needle):
        with pytest.raises(us.StrategyError) as caught:
            us.load(src)
        assert needle in caught.value.message

    def test_a_failure_while_loading_names_the_line(self):
        with pytest.raises(us.StrategyError) as caught:
            us.load("x = 1\ny = 1 / 0\n"
                    "def on_bar(bar, account):\n    return None\n")
        assert caught.value.line == 2

    def test_the_error_is_serialisable_for_the_editor(self):
        with pytest.raises(us.StrategyError) as caught:
            us.load("def on_bar(bar):\n    pass\n")
        assert set(caught.value.to_dict()) == {"message", "line", "offset"}


class TestParams:

    def test_declarations_are_collected_in_order_with_their_bounds(self):
        src = (f"{PREAMBLE}"
               f'W = param.int(100, "Window", min=5, max=500)\n'
               f'M = param.float(0.01, "Min width", min=0.0)\n'
               f'ON = param.bool(True, "Enabled")\n'
               f'MODE = param.choice("fast", "Mode", choices=("fast", "slow"))\n'
               f"def on_bar(bar, account):\n    return hold()\n")
        got = us.collect_params(src)
        assert [(p["label"], p["kind"], p["default"]) for p in got] == [
            ("Window", "int", 100), ("Min width", "float", 0.01),
            ("Enabled", "bool", True), ("Mode", "choice", "fast")]
        assert got[0]["min"] == 5 and got[0]["max"] == 500
        assert "max" not in got[1]
        assert got[3]["choices"] == ["fast", "slow"]

    def test_a_declaration_evaluates_to_its_default(self):
        """`W = param.int(100, ...)` leaves W equal to 100, so the module is
        ordinary Python that runs correctly on its own."""
        src = (f"{PREAMBLE}W = param.int(7, \"Window\")\n"
               f"def on_bar(bar, account):\n    return hold(str(W))\n")
        s = _loaded(src[len(PREAMBLE):])
        _drive(s, [100.0])
        assert s.monitors()["last_decision"] == "7"

    def test_a_choice_that_is_not_among_its_choices_is_refused(self):
        src = (f"{PREAMBLE}M = param.choice(\"x\", \"Mode\", choices=(\"a\",))\n"
               f"def on_bar(bar, account):\n    return hold()\n")
        with pytest.raises(us.StrategyError):
            us.load(src)

    def test_a_broken_source_declares_nothing(self):
        assert us.collect_params("def on_bar(bar):\n    pass\n") == []

    def test_collecting_twice_does_not_accumulate(self):
        src = (f"{PREAMBLE}W = param.int(1, \"Window\")\n"
               f"def on_bar(bar, account):\n    return hold()\n")
        assert len(us.collect_params(src)) == len(us.collect_params(src)) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  Running one
# ═══════════════════════════════════════════════════════════════════════════

class TestSizing:

    def test_an_explicit_count_is_obeyed(self):
        s = _loaded("def on_bar(bar, account):\n    return buy(7)\n")
        assert _drive(s, [100.0])[0][2] == 7

    def test_an_amount_is_divided_by_the_price(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    return buy(amount=10000)\n")
        assert _drive(s, [99.0])[0][2] == 101        # floor(10000 / 99)

    def test_no_size_defers_to_the_risk_budget(self):
        s = _loaded("def on_bar(bar, account):\n    return buy()\n")
        assert _drive(s, [50.0])[0][2] == int(100_000 * 0.20 / 50.0)

    def test_a_limit_price_is_used_for_the_order_and_for_the_size(self):
        s = _loaded("def on_bar(bar, account):\n    return buy(price=50.0)\n")
        _, _, qty, price, _ = _drive(s, [100.0])[0]
        assert (qty, price) == (int(100_000 * 0.20 / 50.0), 50.0)

    def test_shares_and_amount_together_are_refused(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    return buy(3, amount=10)\n")
        assert _drive(s, [100.0]) == []
        assert "TypeError" in s.monitors()["last_decision"] or \
               "not both" in s.monitors()["last_decision"]

    def test_a_size_of_zero_is_declined_with_a_reason(self):
        s = _loaded("def on_bar(bar, account):\n    return buy(0)\n")
        assert _drive(s, [100.0]) == []
        assert "size came out 0" in s.monitors()["last_decision"]

    def test_a_non_positive_price_is_refused(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    return buy(1, price=0.0)\n")
        assert _drive(s, [100.0]) == []
        assert "refusing" in s.monitors()["last_decision"]


class TestWhoseSharesTheseAre:
    """The B1 hazard, closed.

    `ctx.position_qty(symbol)` is the whole account's holding in that symbol.
    A strategy that sold it would sell shares another bot bought, or a
    long-term holding somebody seeded into a paper account, and nothing in the
    chain checked provenance. `account.shares` is this strategy's own count.
    """

    SELL_ALL = ("def on_bar(bar, account):\n"
                "    watch(mine=account.shares)\n"
                "    return sell(reason='all of it') if account.holding "
                "else hold('flat')\n")

    def test_a_strategy_with_no_fills_sees_no_shares(self):
        s = _loaded(self.SELL_ALL)
        assert s.on_bar(_bar(100.0), _ctx([100.0], qty=1000)) == []
        assert s.monitors()["mine"] == 0

    def test_sell_sells_only_what_this_strategy_bought(self):
        s = _loaded(self.SELL_ALL)
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=60, price=100.0,
                       timestamp=T0), _ctx([100.0], qty=1060))
        got = s.on_bar(_bar(100.0, 1), _ctx([100.0] * 2, qty=1060))
        assert [(g.action, g.quantity) for g in got] == [("SELL", 60)]

    def test_selling_returns_the_count_to_zero(self):
        s = _loaded(self.SELL_ALL)
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=60, price=100.0,
                       timestamp=T0), _ctx([100.0], qty=60))
        s.on_fill(Fill(symbol=SYM, action="SELL", quantity=60, price=101.0,
                       timestamp=T0), _ctx([100.0], qty=0))
        assert s.monitors()["own_shares"] == 0
        assert s.monitors()["own_avg_cost"] == 0.0

    def test_it_cannot_ask_for_more_than_the_broker_holds(self):
        """The counter and the broker can disagree after a manual trade or a
        restart, and the broker's number is the one that can be filled."""
        s = _loaded("def on_bar(bar, account):\n    return sell()\n")
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=500, price=100.0,
                       timestamp=T0), _ctx([100.0], qty=500))
        got = s.on_bar(_bar(100.0, 1), _ctx([100.0] * 2, qty=30))
        assert [(g.action, g.quantity) for g in got] == [("SELL", 30)]

    def test_average_cost_is_this_strategy_own(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(cost=account.avg_cost)\n    return hold()\n")
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=10, price=100.0,
                       timestamp=T0), _ctx([100.0], qty=10))
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=10, price=120.0,
                       timestamp=T0), _ctx([100.0], qty=20))
        s.on_bar(_bar(100.0), _ctx([100.0], qty=20))
        assert s.monitors()["cost"] == pytest.approx(110.0)


class TestObservation:

    def test_watched_values_reach_monitors(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(price=bar.close, label='x')\n"
                    "    return hold('nothing')\n")
        _drive(s, [123.456])
        mon = s.monitors()
        assert mon["price"] == pytest.approx(123.456)
        assert mon["label"] == "x"
        assert mon["last_decision"] == "nothing"

    def test_a_watched_name_cannot_overwrite_the_runner_own(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(bars_seen=999)\n    return hold()\n")
        _drive(s, [100.0])
        mon = s.monitors()
        assert mon["bars_seen"] == 1          # the runner's count
        assert mon["w_bars_seen"] == 999      # the strategy's

    @pytest.mark.parametrize("expr,want", [
        ("None", None),
        ("float('nan')", None),
        ("float('inf')", None),
        ("True", True),
        ("3", 3),
    ])
    def test_values_are_coerced_into_something_that_survives_a_wire(
            self, expr, want):
        """A numpy scalar or a nan would otherwise surface as a dead bot
        rather than a bad value, and None is what every indicator returns
        during warm-up."""
        s = _loaded(f"def on_bar(bar, account):\n"
                    f"    watch(v={expr})\n    return hold()\n")
        _drive(s, [100.0])
        assert s.monitors()["v"] == want or s.monitors()["v"] is want

    def test_a_numpy_scalar_becomes_a_float(self):
        s = _loaded("import numpy as np\n"
                    "def on_bar(bar, account):\n"
                    "    watch(v=np.float64(1.5))\n    return hold()\n")
        _drive(s, [100.0])
        assert isinstance(s.monitors()["v"], float)

    def test_plotted_values_are_collected_per_bar(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    plot(upper=bar.close + 1, lower=bar.close - 1)\n"
                    "    return hold()\n")
        _drive(s, [100.0, 200.0])
        assert s.plotted == {"upper": 201.0, "lower": 199.0}

    def test_only_numbers_can_be_plotted(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    plot(ok=1.0, no='text', nope=True)\n"
                    "    return hold()\n")
        _drive(s, [100.0])
        assert s.plotted == {"ok": 1.0}

    def test_returning_none_leaves_the_previous_reason_standing(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    if bar.bars_seen == 1:\n        return hold('first')\n"
                    "    return None\n")
        _drive(s, [100.0, 100.0])
        assert s.monitors()["last_decision"] == "first"

    def test_something_that_is_not_a_decision_is_reported(self):
        s = _loaded("def on_bar(bar, account):\n    return 42\n")
        assert _drive(s, [100.0]) == []
        assert "not a decision" in s.monitors()["last_decision"]


class TestState:

    def test_values_survive_between_bars(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    state.n = (state.n or 0) + 1\n"
                    "    watch(n=state.n)\n    return hold()\n")
        _drive(s, [100.0] * 5)
        assert s.monitors()["n"] == 5

    def test_an_unset_value_reads_as_none_rather_than_raising(self):
        """The first bar always reads before it writes."""
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(seen=state.never_set)\n    return hold()\n")
        _drive(s, [100.0])
        assert s.monitors()["seen"] is None

    def test_on_start_clears_it_so_a_rerun_does_not_inherit(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    state.n = (state.n or 0) + 1\n"
                    "    watch(n=state.n)\n    return hold()\n")
        _drive(s, [100.0] * 3)
        s.on_start(_ctx([]))
        _drive(s, [100.0])
        assert s.monitors()["n"] == 1

    def test_init_runs_once_before_the_first_bar(self):
        s = _loaded("def init():\n    state.ready = 'yes'\n"
                    "def on_bar(bar, account):\n"
                    "    watch(ready=state.ready)\n    return hold()\n")
        _drive(s, [100.0])
        assert s.monitors()["ready"] == "yes"


class TestFailure:
    """A strategy that raises must cost a bar, not the run."""

    def test_the_bar_is_lost_and_the_run_continues(self):
        s = _loaded("def on_bar(bar, account):\n    return 1 / 0\n")
        for i in range(3):
            assert s.on_bar(_bar(100.0, i), _ctx([100.0] * (i + 1))) == []
        assert s.monitors()["errors"] == 3

    def test_the_reason_names_the_line_in_the_user_file(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    x = 1\n"
                    "    return x / 0\n")
        _drive(s, [100.0])
        assert "line 4" in s.monitors()["last_decision"]   # 1 for the preamble

    def test_it_stops_being_retried_rather_than_logging_once_a_bar(self):
        """22,000 identical tracebacks in a 120-day replay say no more than
        the first one did, and bury everything else."""
        s = _loaded("def on_bar(bar, account):\n    return 1 / 0\n")
        for i in range(us.MAX_CONSECUTIVE_ERRORS + 5):
            s.on_bar(_bar(100.0, i), _ctx([100.0] * (i + 1)))
        assert s.monitors()["errors"] == us.MAX_CONSECUTIVE_ERRORS
        assert "raised" in s.monitors()["disabled"]

    def test_an_occasional_failure_does_not_disable_it(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    if bar.bars_seen % 2:\n        return 1 / 0\n"
                    "    return hold('fine')\n")
        for i in range(20):
            s.on_bar(_bar(100.0, i), _ctx([100.0] * (i + 1)))
        assert "disabled" not in s.monitors()
        assert s.monitors()["errors"] == 10

    def test_a_raising_hook_does_not_stop_the_fill_bookkeeping(self):
        s = _loaded("def on_bar(bar, account):\n    return hold()\n"
                    "def on_fill(fill, account):\n    raise RuntimeError('x')\n")
        s.on_fill(Fill(symbol=SYM, action="BUY", quantity=5, price=100.0,
                       timestamp=T0), _ctx([100.0], qty=5))
        assert s.monitors()["own_shares"] == 5


class TestBar:

    def test_closes_is_oldest_first_so_indicators_read_normally(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(last=bar.closes[-1], first=bar.closes[0])\n"
                    "    return hold()\n")
        _drive(s, [10.0, 20.0, 30.0])
        assert (s.monitors()["last"], s.monitors()["first"]) == (30.0, 10.0)

    def test_ago_counts_backwards_from_this_bar(self):
        s = _loaded("def on_bar(bar, account):\n"
                    "    watch(now=bar.ago(0), prev=bar.ago(1), far=bar.ago(99))\n"
                    "    return hold()\n")
        _drive(s, [10.0, 20.0])
        mon = s.monitors()
        assert (mon["now"], mon["prev"]) == (20.0, 10.0)
        assert mon["far"] is None          # not an IndexError on bar 1

    def test_the_day_extremes_are_named_for_what_they_are(self):
        """One sample per bar means a per-bar high and low do not exist; these
        are the trading day's, which is what the Snapshot carries."""
        assert "day_high" in authoring.Bar.__annotations__
        assert "high" not in authoring.Bar.__annotations__


class TestIndicators:

    @pytest.mark.parametrize("name", ["adx", "atr", "stoch"])
    def test_the_ones_needing_a_bar_range_refuse_and_explain(self, name):
        with pytest.raises(AttributeError) as caught:
            getattr(authoring.ta, name)
        assert "high and low" in str(caught.value)
        assert "ta.efficiency" in str(caught.value)

    def test_an_unknown_indicator_lists_the_real_ones(self):
        with pytest.raises(AttributeError) as caught:
            authoring.ta.nonsense
        assert "efficiency" in str(caught.value)

    @pytest.mark.parametrize("call,want", [
        ("ta.bb([1.0, 2.0], 20)", (None, None, None)),
        ("ta.sma([1.0], 20)", None),
        ("ta.ema([1.0], 20)", None),
        ("ta.rsi([1.0, 2.0], 14)", None),
        ("ta.macd([1.0] * 5)", (None, None, None)),
        ("ta.wma([1.0], 20)", None),
        ("ta.efficiency([1.0], 14)", None),
    ])
    def test_warm_up_returns_none_rather_than_nan(self, call, want):
        """Which removes the length check and the `[-1]` from every strategy,
        and with them the commonest mistake: reading nan."""
        assert eval(call, {"ta": authoring.ta}) == want

    def test_the_indicators_return_the_latest_value_not_an_array(self):
        closes = [float(i) for i in range(60)]
        assert isinstance(authoring.ta.sma(closes, 20), float)
        upper, middle, lower = authoring.ta.bb(closes, 20)
        assert lower < middle < upper

    @pytest.mark.parametrize("closes,want", [
        ([float(i) for i in range(20)], 100.0),      # a clean trend
        ([5.0] * 20, 0.0),                           # no movement at all
    ])
    def test_efficiency_is_a_zero_to_one_hundred_scale(self, closes, want):
        assert authoring.ta.efficiency(closes, 14) == want

    def test_highest_and_lowest_are_donchian_edges(self):
        closes = [1.0, 9.0, 3.0, 7.0, 5.0]
        assert authoring.ta.highest(closes, 3) == 7.0
        assert authoring.ta.lowest(closes, 3) == 3.0


class TestTheContract:
    """What the editor's completion list and every saved strategy depend on."""

    def test_the_vocabulary_is_exactly_this(self):
        """A rename here breaks every strategy anybody has saved, so it should
        be a deliberate edit to this list rather than a surprise."""
        assert sorted(authoring.__all__) == sorted([
            "buy", "sell", "hold", "watch", "plot", "state", "param", "ta",
            "Bar", "Account", "Fill", "Intent", "math", "datetime",
        ])

    def test_the_vocabulary_imports_nothing_that_can_trade(self):
        """No name in a strategy's namespace reaches a broker session.

        beginner.py's `buy()` calls `client.buy_stock` -- right for a human at
        a REPL, and in a bot it would give every bot process its own broker
        session and put every order outside the RiskGate. Asserted against
        authoring.py's own import statements rather than against sys.modules,
        because `cjtrade/__init__.py` imports the shell and therefore loads a
        broker client into any process that touches this package. That is why
        this is not a sandbox and does not claim to be: it stops accidents and
        bounds the completion list, nothing more.
        """
        import ast

        tree = ast.parse(open(authoring.__file__, encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")

        banned = ("brokers", "dotenv", "requests", "httpx", "socket",
                  "urllib", "shioaji", "subprocess")
        offenders = [m for m in imported
                     if any(b in m.split(".") or b in m for b in banned)]
        assert offenders == [], f"authoring.py imports {offenders}"

    def test_no_attribute_of_the_vocabulary_holds_a_client(self):
        """A shallow sweep, because `ta` and `param` are instances: an object
        with a broker client hanging off it would be reachable as
        `ta.something.buy_stock` without any import appearing above."""
        for name in authoring.__all__:
            obj = getattr(authoring, name)
            if name in ("math", "datetime"):
                continue          # stdlib modules, deliberately offered
            for attr in dir(obj):
                if attr.startswith("_"):
                    continue
                try:
                    value = getattr(obj, attr)
                except AttributeError:
                    continue      # ta.adx and friends refuse on purpose
                assert not hasattr(value, "buy_stock"), f"{name}.{attr}"
                assert not hasattr(value, "place_order"), f"{name}.{attr}"

    def test_buy_and_sell_return_an_intent_rather_than_doing_anything(self):
        assert isinstance(authoring.buy(), authoring.Intent)
        assert isinstance(authoring.sell(), authoring.Intent)
        assert authoring.buy().action == "BUY"
        assert authoring.sell().action == "SELL"

    def test_the_api_reference_describes_every_public_name(self):
        entries = us.api_reference()
        top = {e["qualified"] for e in entries if "." not in e["qualified"]}
        assert top == set(authoring.__all__)
        assert all(e["signature"] for e in entries)

    def test_the_reference_offers_only_the_usable_indicators(self):
        offered = {e["name"] for e in us.api_reference()
                   if e["qualified"].startswith("ta.")}
        assert offered == {"bb", "ema", "sma", "rsi", "macd", "wma",
                           "highest", "lowest", "efficiency"}
        assert not offered & {"adx", "atr", "stoch"}

    def test_buy_is_documented_because_the_editor_shows_the_docstring(self):
        buy = next(e for e in us.api_reference() if e["qualified"] == "buy")
        assert "shares" in buy["signature"]
        assert buy["doc"]


class TestStarterTemplate:

    def test_it_carries_the_name_and_symbol_the_user_chose(self):
        src = us.starter_source("Fade the band", "2330")
        assert "Fade the band — 2330" in src

    def test_it_has_the_import_line_the_static_analysers_need(self):
        """Pyright cannot see names injected into a namespace, so a file
        without this gets no completion and a squiggle on every call."""
        assert us.AUTHORING_MODULE in us.starter_source()

    def test_it_runs_and_trades_rather_than_being_a_skeleton(self):
        """The first thing anyone does is press run, and a file that does
        nothing teaches nothing about what went wrong."""
        s = us.load(us.starter_source("T", SYM))
        s.on_start(_ctx([], params={"risk__max_position_pct": 0.20}))
        # 100 bars of ±1 around 100 give bands at roughly 98 and 102, so the
        # bandwidth clears the template's 1% squeeze floor. A flat series
        # would not: zero width is a squeeze, and the template declines it.
        closes = [100.0 + (1.0 if i % 2 else -1.0) for i in range(100)]
        closes.append(90.0)                    # well through the lower band
        signals = _drive(s, closes)
        assert signals, s.monitors()["last_decision"]
        assert [(a, p) for _, a, _, p, _ in signals] == [("BUY", 90.0)]
        assert "lower band touch" in signals[0][4]

    def test_it_declares_its_parameters(self):
        assert [p["label"] for p in
                us.collect_params(us.starter_source())] == [
            "Bollinger window", "Minimum band width"]
