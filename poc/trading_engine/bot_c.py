"""
poc/trading_engine/bot_c.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bollinger Band mean reversion on a single symbol.

Everything that is not the strategy choice lives in bot_runner.py -- sockets,
sequence checking, the ledger mirror, the status report. This file is the whole
of what makes this bot different from bot_a and bot_b.
"""
from bot_runner import run_bot
from cjtrade.pkgs.strategy.bb import BollingerStrategy

SYMBOL = "2317"

PARAMS = {
    "bb__min_width_pct": 0.01,
    "bb__window_size": 100,
    # Fraction of equity per position, read by calc_qty (base_strategy.py).
    # The strategy's own default is 0.05, which against the backtest
    # backend's 100,000 account sizes a 20-share order -- and commission is
    # max(notional * 0.1425%, NT$20), so 20 shares pay the NT$20 floor:
    # 1.100% of notional round trip instead of the statutory 0.585%. The
    # floor stops biting at 57 shares (notional 14,035), so 0.20 -> 80
    # shares buys the whole of that saving.
    #
    # It does not make this strategy profitable. 0.585% is the floor from
    # 0.1425% commission twice plus 0.3% transaction tax, and a one-tick
    # target on a 250 stock is 0.4%. Size fixes the penalty, not the edge.
    "risk__max_position_pct": 0.20,
}


if __name__ == "__main__":
    run_bot(BollingerStrategy(), SYMBOL, PARAMS)
