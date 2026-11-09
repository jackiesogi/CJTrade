"""Unit tests for the pre-trade risk gate."""
import pytest
from cjtrade.pkgs.risk import RiskGate
from cjtrade.pkgs.risk import RiskLimits


def _gate(**kw) -> RiskGate:
    equity = kw.pop("initial_equity", 1_000_000.0)
    return RiskGate(RiskLimits(**kw), initial_equity=equity)


# ── everything off by default ─────────────────────────────────────────────────

class TestDefaultsAreOff:
    def test_no_limits_allows_everything(self):
        g = _gate()
        for _ in range(100):
            assert g.check("Bot_A", "2317", "BUY", 10_000, 240.0) is None
            g.record_submitted("Bot_A", "2317", "BUY", 10_000, 240.0)

    def test_not_halted_initially(self):
        g = _gate()
        assert g.halted is False
        assert g.halt_reason is None


# ── per-bot allocation ────────────────────────────────────────────────────────

class TestNotionalPerBot:
    def test_allows_up_to_the_allocation(self):
        g = _gate(max_notional_per_bot=10_000.0)
        assert g.check("Bot_A", "2317", "BUY", 40, 250.0) is None    # 10,000 exactly

    def test_refuses_what_would_exceed_it(self):
        g = _gate(max_notional_per_bot=10_000.0)
        reason = g.check("Bot_A", "2317", "BUY", 41, 250.0)
        assert reason is not None and "allocation" in reason

    def test_exposure_accumulates_across_orders(self):
        g = _gate(max_notional_per_bot=10_000.0)
        g.record_submitted("Bot_A", "2317", "BUY", 20, 250.0)        # 5,000
        assert g.exposure("Bot_A") == 5_000.0
        assert g.check("Bot_A", "2317", "BUY", 20, 250.0) is None    # 10,000 total
        g.record_submitted("Bot_A", "2317", "BUY", 20, 250.0)
        assert g.check("Bot_A", "2317", "BUY", 1, 250.0) is not None

    def test_allocations_are_independent_per_bot(self):
        g = _gate(max_notional_per_bot=10_000.0)
        g.record_submitted("Bot_A", "2317", "BUY", 40, 250.0)
        assert g.check("Bot_A", "2317", "BUY", 1, 250.0) is not None
        assert g.check("Bot_B", "2317", "BUY", 40, 250.0) is None

    def test_a_dead_buy_releases_its_capital(self):
        g = _gate(max_notional_per_bot=10_000.0)
        g.record_submitted("Bot_A", "2317", "BUY", 40, 250.0)
        assert g.check("Bot_A", "2317", "BUY", 1, 250.0) is not None
        g.record_outcome("Bot_A", "BUY", 10_000.0, filled=False)     # cancelled
        assert g.exposure("Bot_A") == 0.0
        assert g.check("Bot_A", "2317", "BUY", 40, 250.0) is None

    def test_a_filled_buy_keeps_holding_the_capital(self):
        g = _gate(max_notional_per_bot=10_000.0)
        g.record_submitted("Bot_A", "2317", "BUY", 40, 250.0)
        g.record_outcome("Bot_A", "BUY", 10_000.0, filled=True)
        # The notional moved from resting to held; it is still deployed.
        assert g.exposure("Bot_A") == 10_000.0
        assert g.check("Bot_A", "2317", "BUY", 1, 250.0) is not None

    def test_a_filled_sell_frees_the_capital(self):
        g = _gate(max_notional_per_bot=10_000.0)
        g.record_submitted("Bot_A", "2317", "BUY", 40, 250.0)
        g.record_outcome("Bot_A", "BUY", 10_000.0, filled=True)
        g.record_submitted("Bot_A", "2317", "SELL", 40, 250.0)
        g.record_outcome("Bot_A", "SELL", 10_000.0, filled=True)
        assert g.exposure("Bot_A") == 0.0

    def test_sells_are_never_budget_checked(self):
        g = _gate(max_notional_per_bot=1.0)
        assert g.check("Bot_A", "2317", "SELL", 10_000, 250.0) is None

    def test_rounding_drift_does_not_strand_a_bot(self):
        g = _gate(max_notional_per_bot=1_000.0)
        for _ in range(3):
            g.record_submitted("Bot_A", "2317", "BUY", 1, 33.333333)
            g.record_outcome("Bot_A", "BUY", 33.333333, filled=False)
        assert g.exposure("Bot_A") == 0.0


# ── order rate ────────────────────────────────────────────────────────────────

class TestOrdersPerBar:
    def test_allows_up_to_the_cap_then_refuses(self):
        g = _gate(max_orders_per_bar=2)
        g.start_bar(0)
        for _ in range(2):
            assert g.check("Bot_A", "2317", "BUY", 1, 10.0) is None
            g.record_submitted("Bot_A", "2317", "BUY", 1, 10.0)
        reason = g.check("Bot_A", "2317", "BUY", 1, 10.0)
        assert reason is not None and "this bar" in reason

    def test_resets_on_the_next_bar(self):
        g = _gate(max_orders_per_bar=1)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 1, 10.0)
        assert g.check("Bot_A", "2317", "BUY", 1, 10.0) is not None
        g.start_bar(1)
        assert g.check("Bot_A", "2317", "BUY", 1, 10.0) is None

    def test_counted_per_bot(self):
        g = _gate(max_orders_per_bar=1)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 1, 10.0)
        assert g.check("Bot_A", "2317", "BUY", 1, 10.0) is not None
        assert g.check("Bot_B", "2317", "BUY", 1, 10.0) is None


# ── duplicates ────────────────────────────────────────────────────────────────

class TestDuplicates:
    def test_identical_order_inside_the_window_is_refused(self):
        g = _gate(duplicate_window_bars=3)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 20, 240.0)
        g.start_bar(1)
        reason = g.check("Bot_A", "2317", "BUY", 20, 240.0)
        assert reason is not None and "duplicate" in reason

    def test_allowed_again_once_the_window_passes(self):
        g = _gate(duplicate_window_bars=3)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 20, 240.0)
        g.start_bar(3)
        assert g.check("Bot_A", "2317", "BUY", 20, 240.0) is None

    @pytest.mark.parametrize("field,value", [
        ("symbol", "2330"), ("action", "SELL"), ("quantity", 21), ("price", 241.0),
    ])
    def test_any_differing_field_makes_it_a_new_order(self, field, value):
        g = _gate(duplicate_window_bars=3)
        base = dict(symbol="2317", action="BUY", quantity=20, price=240.0)
        g.start_bar(0)
        g.record_submitted("Bot_A", **base)
        g.start_bar(1)
        assert g.check("Bot_A", **{**base, field: value}) is None

    def test_another_bot_sending_the_same_order_is_not_a_duplicate(self):
        g = _gate(duplicate_window_bars=3)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 20, 240.0)
        g.start_bar(1)
        assert g.check("Bot_B", "2317", "BUY", 20, 240.0) is None

    def test_zero_window_disables_the_check(self):
        g = _gate(duplicate_window_bars=0)
        g.start_bar(0)
        g.record_submitted("Bot_A", "2317", "BUY", 20, 240.0)
        assert g.check("Bot_A", "2317", "BUY", 20, 240.0) is None


# ── kill switch ───────────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_does_not_trip_above_the_floor(self):
        g = _gate(max_loss_pct=0.10, initial_equity=1_000.0)
        assert g.observe_equity(900.0) is None     # exactly at the floor
        assert g.halted is False

    def test_trips_below_the_floor(self):
        g = _gate(max_loss_pct=0.10, initial_equity=1_000.0)
        reason = g.observe_equity(899.0)
        assert reason is not None and "loss limit" in reason
        assert g.halted is True

    def test_refuses_everything_once_halted(self):
        g = _gate(max_loss_pct=0.10, initial_equity=1_000.0)
        g.observe_equity(0.0)
        reason = g.check("Bot_A", "2317", "SELL", 1, 1.0)
        assert reason is not None and "halted" in reason

    def test_reports_the_trip_only_once(self):
        """So a caller can treat a truthy return as "shut down now"."""
        g = _gate(max_loss_pct=0.10, initial_equity=1_000.0)
        assert g.observe_equity(0.0) is not None
        assert g.observe_equity(0.0) is None
        assert g.halted is True

    def test_off_when_unset(self):
        g = _gate(initial_equity=1_000.0)
        assert g.observe_equity(0.0) is None
        assert g.halted is False

    def test_manual_halt(self):
        g = _gate()
        g.halt("operator stopped trading")
        assert g.halted is True
        assert "operator" in g.check("Bot_A", "2317", "BUY", 1, 1.0)


if __name__ == "__main__":
    pytest.main([__file__])
