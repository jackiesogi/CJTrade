"""The demo backend's random start must not depend on a bound it can exceed.

_initialize_market_time places the simulated "now" some days in the past so the
preload window fits inside data that exists. It did that with
``random.randint(self.num_days_preload, 20)``, which raises ValueError the
moment num_days_preload passes 20 -- out of __init__, so the whole server
failed to start. The shipped demo.cjsys value is 11, sitting just inside the
limit, so nothing noticed.
"""
import pytest
from cjtrade.apps.ArenaX.demo_backend import _MAX_DAYS_BACK
from cjtrade.apps.ArenaX.demo_backend import ArenaX_Backend_None


def _backend(num_days_preload):
    b = ArenaX_Backend_None.__new__(ArenaX_Backend_None)   # no __init__: no clock, no disk
    b.num_days_preload = num_days_preload
    return b


class TestRandomDaysBack:
    @pytest.mark.parametrize("n", [1, 3, 11, 20, 21, 30, 300, 365])
    def test_never_raises(self, n):
        assert _backend(n)._random_days_back() >= 1

    @pytest.mark.parametrize("n", [1, 3, 11, 20])
    def test_within_bounds_it_stays_within_bounds(self, n):
        b = _backend(n)
        got = {b._random_days_back() for _ in range(300)}
        assert min(got) >= n
        assert max(got) <= _MAX_DAYS_BACK

    @pytest.mark.parametrize("n", [1, 3, 11])
    def test_is_actually_random_when_there_is_room(self, n):
        b = _backend(n)
        assert len({b._random_days_back() for _ in range(300)}) > 1

    @pytest.mark.parametrize("n", [21, 30, 300, 365])
    def test_preload_wins_when_the_bounds_conflict(self, n):
        """No value is both >= 300 and <= 20. Honour the preload: starting
        inside the window would replay off the end of the data."""
        b = _backend(n)
        assert {b._random_days_back() for _ in range(50)} == {n}

    def test_zero_preload_still_yields_a_usable_day_count(self):
        b = _backend(0)
        got = {b._random_days_back() for _ in range(200)}
        assert min(got) >= 1
        assert max(got) <= _MAX_DAYS_BACK
