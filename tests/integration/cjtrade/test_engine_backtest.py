"""The trading engine, end to end, on 10 recorded days of 2357.

Same bars in, same orders out: the replay is reproducible, so the fills are
compared exactly against a recorded run. If a change is meant to alter how
the engine trades, re-record ``EXPECTED_FILLS`` and ``EXPECTED_EQUITY`` and
say why in the commit.
"""
import pytest

FUND = 1_000_000                   # --fund and AX_INITIAL_BALANCE in conftest.py

# (time, action, quantity, price); a sell's quantity is negative.
EXPECTED_FILLS = [
    ("2024-04-29 09:54", "BUY", 470, 425),
    ("2024-04-29 09:57", "BUY", 470, 425.5),
    ("2024-04-29 10:00", "BUY", 469, 426),
    ("2024-04-29 11:47", "BUY", 469, 426),
    ("2024-05-02 09:07", "SELL", -1878, 431),
    ("2024-05-03 09:40", "BUY", 466, 431),
    ("2024-05-03 09:44", "BUY", 465, 431.5),
    ("2024-05-03 10:06", "SELL", -931, 430.5),
    ("2024-05-06 09:23", "BUY", 461, 434.5),
    ("2024-05-06 09:51", "BUY", 459, 436.5),
    ("2024-05-06 09:54", "BUY", 459, 437),
    ("2024-05-06 10:02", "BUY", 457, 440.5),
    ("2024-05-07 09:30", "SELL", -1836, 458),
    ("2024-05-08 09:42", "BUY", 450, 460),
    ("2024-05-08 09:57", "SELL", -450, 454.5),
    ("2024-05-08 10:31", "BUY", 452, 456),
    ("2024-05-08 11:03", "BUY", 450, 458.5),
]
EXPECTED_EQUITY = 1_032_671.86     # +3.27%
EXPECTED_BARS = 1765               # 8 sessions; 2024-05-01 is a holiday


def test_the_engine_exits_cleanly(engine_run):
    assert engine_run.returncode == 0, engine_run.engine_log[-3000:]


@pytest.mark.parametrize("log", ["engine_log", "server_log"])
def test_nothing_raises_in_either_process(engine_run, log):
    assert "Traceback" not in getattr(engine_run, log)


def test_every_bar_of_the_window_is_replayed(engine_run):
    curve = engine_run.result.equity_curve
    assert len(curve) == EXPECTED_BARS
    assert curve[0]["time"] == "2024-04-29T09:01:00"


def test_the_bot_trades_exactly_as_recorded(engine_run):
    fills = [(f["time"][:16].replace("T", " "), f["action"], f["quantity"], f["price"])
             for f in engine_run.result.fill_history]
    assert fills == EXPECTED_FILLS


def test_every_fill_pays_commission_and_every_sell_pays_tax(engine_run):
    for f in engine_run.result.fill_history:
        assert f["commission"] >= 20          # TWSE minimum commission
        assert (f["tax"] > 0) == (f["action"] == "SELL")


def test_the_run_ends_with_the_recorded_equity(engine_run):
    result = engine_run.result
    assert result.initial_balance == FUND
    assert result.final_equity == pytest.approx(EXPECTED_EQUITY, abs=0.01)


def test_the_window_stays_profitable_with_a_small_drawdown(engine_run):
    # Daily closes, the resolution the report's max drawdown uses (-0.47%).
    daily = engine_run.result.to_daily_equity()
    drawdown = (daily / daily.cummax() - 1).min()
    assert daily.iloc[-1] > FUND
    assert drawdown > -0.01
