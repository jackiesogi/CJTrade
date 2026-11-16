"""DCA_Monthly — one instalment per calendar month, and no drift.

This strategy used to wait `timedelta(days=30)` between purchases, which slides
the instalment earlier every month (5 Jan, 4 Feb, 6 Mar, ...) and fits 12.2
instalments into a year instead of 12. The rule is now "the first bar of a
calendar month this strategy is given", which also needs no trading calendar:
a 1st that is a weekend or a holiday resolves itself, because the month rolls
over on whatever bar actually arrives.

Verified against real data as well as these fixtures: over 2026-05 to 2026-08
of the local 1m price DB the four instalments landed on 2026-05-04 (1 May is
Labour Day), 06-01, 07-01 and 2026-08-03 (1 Aug is a Saturday).
"""
from datetime import datetime
from datetime import timedelta

import pytest
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.strategy.dca import DCA_Monthly

SYM = "0050"
AMOUNT = 10_000.0


def _ctx(ts, prices, *, params=None, equity=1_000_000.0, positions=None):
    from cjtrade.pkgs.strategy.base_strategy import StrategyContext
    return StrategyContext(
        timestamp=ts, balance=equity, equity=equity,
        positions=positions or [], price_history={SYM: list(prices)},
        bar_index=len(prices),
        params=params if params is not None else {"dca__amount": AMOUNT},
    )


def _bar(ts, close, symbol=SYM) -> Kbar:
    return Kbar(timestamp=ts, open=close, high=close, low=close, close=close,
                volume=100, symbol=symbol)


def _started(params=None) -> DCA_Monthly:
    s = DCA_Monthly()
    s.on_start(_ctx(datetime(2026, 1, 1), [], params=params))
    return s


def _feed(strategy, bars, params=None):
    """Drive the strategy over (timestamp, close) pairs; return every BUY as
    (iso timestamp, quantity)."""
    buys, prices = [], []
    for ts, close in bars:
        prices.append(close)
        for sig in strategy.on_bar(_bar(ts, close),
                                   _ctx(ts, prices, params=params)) or []:
            buys.append((ts.strftime("%Y-%m-%d %H:%M"), sig.quantity))
    return buys


def _sessions(start, end, *, price=50.0):
    """One bar a minute, 09:00-13:30, weekdays only."""
    ts = start
    while ts < end:
        if ts.weekday() < 5 and 9 <= ts.hour < 14:
            yield ts, price
        ts += timedelta(minutes=1)


class TestMonthlyCadence:

    def test_buys_on_the_first_bar_it_ever_sees(self):
        s = _started()
        buys = _feed(s, [(datetime(2026, 1, 5, 9, 1), 50.0)])
        assert [b[0] for b in buys] == ["2026-01-05 09:01"]

    def test_one_instalment_per_calendar_month(self):
        s = _started()
        buys = _feed(s, _sessions(datetime(2026, 1, 5, 9, 1),
                                  datetime(2026, 4, 2, 14, 0)))
        assert [b[0] for b in buys] == [
            "2026-01-05 09:01",   # first bar of the run
            "2026-02-02 09:00",   # 1 Feb 2026 is a Sunday
            "2026-03-02 09:00",   # 1 Mar 2026 is a Sunday
            "2026-04-01 09:00",
        ]

    def test_does_not_drift_the_way_a_30_day_rule_does(self):
        """A 30-day rule starting 5 Jan gives 4 Feb, 6 Mar, 5 Apr: the day of
        month walks backwards and then forwards. Calendar months cannot."""
        s = _started()
        buys = _feed(s, _sessions(datetime(2026, 1, 5, 9, 1),
                                  datetime(2026, 7, 1, 0, 0)))
        assert len(buys) == 6                      # Jan..Jun, exactly one each
        assert sorted({b[0][:7] for b in buys}) == [
            "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

    def test_a_closed_first_of_month_falls_through_to_the_next_session(self):
        """No holiday table involved: the month rolls over on the first bar
        that arrives, so a shut 1st needs no special case."""
        s = _started()
        # 1-3 May absent entirely, as if the exchange were closed.
        bars = [(datetime(2026, 4, 30, 9, 1), 50.0),
                (datetime(2026, 5, 4, 9, 1), 50.0),
                (datetime(2026, 5, 4, 9, 2), 50.0)]
        buys = _feed(s, bars)
        assert [b[0] for b in buys] == ["2026-04-30 09:01", "2026-05-04 09:01"]

    def test_every_other_bar_in_the_month_is_declined_with_a_reason(self):
        s = _started()
        _feed(s, [(datetime(2026, 1, 5, 9, 1), 50.0),
                  (datetime(2026, 1, 5, 9, 2), 50.0)])
        assert s.monitors()["last_decision"] == "already bought 0050 in 2026-01"


class TestSizing:

    def test_quantity_is_whole_shares_of_a_fixed_sum(self):
        s = _started()
        buys = _feed(s, [(datetime(2026, 1, 5, 9, 1), 101.60)])
        assert buys == [("2026-01-05 09:01", 98)]      # floor(10000 / 101.6)

    def test_instalment_does_not_scale_with_equity(self):
        """The point of DCA: the instalment is a property of the saver's
        income, not of how the portfolio has done since the last one."""
        s = _started()
        prices = [50.0]
        poor = s.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 50.0),
                        _ctx(datetime(2026, 1, 5, 9, 1), prices, equity=50_000.0))
        s2 = _started()
        rich = s2.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 50.0),
                         _ctx(datetime(2026, 1, 5, 9, 1), prices,
                              equity=50_000_000.0))
        assert poor[0].quantity == rich[0].quantity == 200

    def test_amount_comes_from_params(self):
        s = _started(params={"dca__amount": 3_000.0})
        buys = _feed(s, [(datetime(2026, 1, 5, 9, 1), 50.0)],
                     params={"dca__amount": 3_000.0})
        assert buys == [("2026-01-05 09:01", 60)]

    def test_legacy_param_spelling_still_read(self):
        s = _started(params={"dca_amount": 3_000.0})
        assert s.monitors()["amount"] == 3_000.0


class TestUnaffordable:

    def test_no_signal_when_one_share_costs_more_than_an_instalment(self):
        s = _started(params={"dca__amount": 100.0})
        got = s.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 250.0),
                       _ctx(datetime(2026, 1, 5, 9, 1), [250.0],
                            params={"dca__amount": 100.0}))
        assert got == []
        assert "unaffordable" in s.monitors()["last_decision"]

    def test_the_month_is_not_consumed_so_a_cheaper_bar_still_buys(self):
        p = {"dca__amount": 100.0}
        s = _started(params=p)
        s.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 250.0),
                 _ctx(datetime(2026, 1, 5, 9, 1), [250.0], params=p))
        got = s.on_bar(_bar(datetime(2026, 1, 6, 9, 1), 90.0),
                       _ctx(datetime(2026, 1, 6, 9, 1), [250.0, 90.0], params=p))
        assert len(got) == 1 and got[0].quantity == 1

    def test_counted_once_per_month_not_once_per_bar(self):
        p = {"dca__amount": 100.0}
        s = _started(params=p)
        for i in range(50):
            ts = datetime(2026, 1, 5, 9, 1) + timedelta(minutes=i)
            s.on_bar(_bar(ts, 250.0), _ctx(ts, [250.0] * (i + 1), params=p))
        assert s.monitors()["months_unaffordable"] == 1

    def test_a_non_positive_price_is_declined_not_divided_by(self):
        s = _started()
        assert s.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 0.0),
                        _ctx(datetime(2026, 1, 5, 9, 1), [0.0])) == []
        assert "no usable price" in s.monitors()["last_decision"]


class TestResume:

    def test_a_seeded_last_buy_consumes_that_month(self):
        p = {"dca__amount": AMOUNT,
             "dca__last_buy_time": {SYM: "2026-01-04T09:30:00"}}
        s = _started(params=p)
        assert s.on_bar(_bar(datetime(2026, 1, 10, 9, 1), 50.0),
                        _ctx(datetime(2026, 1, 10, 9, 1), [50.0], params=p)) == []
        assert len(s.on_bar(_bar(datetime(2026, 2, 2, 9, 1), 50.0),
                            _ctx(datetime(2026, 2, 2, 9, 1), [50.0] * 2,
                                 params=p))) == 1

    @pytest.mark.parametrize("seed", ["nonsense", None, 42, ""])
    def test_an_unparseable_seed_is_ignored_rather_than_fatal(self, seed):
        p = {"dca__last_buy_time": {SYM: seed}}
        s = _started(params=p)
        assert len(s.on_bar(_bar(datetime(2026, 1, 5, 9, 1), 50.0),
                            _ctx(datetime(2026, 1, 5, 9, 1), [50.0],
                                 params=p))) == 1

    def test_last_buy_is_exposed_for_handing_back(self):
        s = _started()
        _feed(s, [(datetime(2026, 1, 5, 9, 1), 50.0)])
        assert s.last_buy(SYM) == datetime(2026, 1, 5, 9, 1)
        assert s.last_buy("9999") is None


class TestPerSymbol:

    def test_each_symbol_gets_its_own_instalment(self):
        s = _started()
        ts = datetime(2026, 1, 5, 9, 1)
        ctx = _ctx(ts, [50.0])
        a = s.on_bar(_bar(ts, 50.0, "0050"), ctx)
        b = s.on_bar(_bar(ts, 50.0, "2330"), ctx)
        assert len(a) == 1 and len(b) == 1
        assert s.monitors()["instalments"] == 2

    def test_one_symbol_being_bought_does_not_consume_another(self):
        s = _started()
        ts = datetime(2026, 1, 5, 9, 1)
        s.on_bar(_bar(ts, 50.0, "0050"), _ctx(ts, [50.0]))
        later = datetime(2026, 1, 20, 9, 1)
        assert len(s.on_bar(_bar(later, 50.0, "2330"),
                            _ctx(later, [50.0] * 2))) == 1


class TestNeverSells:

    def test_only_ever_emits_buy_however_the_price_moves(self):
        s = _started()
        actions = set()
        held = [{"symbol": SYM, "quantity": 1000, "avg_cost": 50.0,
                 "current_price": 50.0, "market_value": 50_000.0,
                 "unrealized_pnl": 0.0}]
        for i in range(400):
            ts = datetime(2026, 1, 5, 9, 1) + timedelta(days=i)
            price = 50.0 + (i % 40) - 20            # swings hard both ways
            for sig in s.on_bar(_bar(ts, price),
                                _ctx(ts, [price], positions=held)) or []:
                actions.add(sig.action)
        assert actions == {"BUY"}


class TestMonitors:

    def test_safe_to_call_before_the_first_bar(self):
        mon = DCA_Monthly().monitors()
        assert mon["bars_seen"] == 0
        assert mon["last_buy"] == "never"
        assert mon["avg_cost"] == 0.0

    def test_values_are_wire_safe_scalars(self):
        s = _started()
        _feed(s, _sessions(datetime(2026, 1, 5, 9, 1),
                           datetime(2026, 3, 2, 14, 0)))
        mon = s.monitors()
        assert all(isinstance(v, (int, float, str)) for v in mon.values()), mon

    def test_reports_what_was_actually_deployed(self):
        s = _started()
        _feed(s, [(datetime(2026, 1, 5, 9, 1), 50.0),
                  (datetime(2026, 2, 2, 9, 1), 100.0)])
        mon = s.monitors()
        assert mon["instalments"] == 2
        assert mon["shares_bought"] == 200 + 100
        assert mon["cash_deployed"] == pytest.approx(200 * 50.0 + 100 * 100.0)
        # Rounded to 2dp by monitors(), because these go on a wire.
        assert mon["avg_cost"] == round(20_000.0 / 300, 2)
        assert mon["last_buy"] == "2026-02-02 09:01"
