"""
poc/trading_engine/bot_a.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Monthly dollar-cost averaging on a broad-market ETF.

Buys a fixed NT$ amount on the first bar of each calendar month and never
sells, so it is the accumulate-and-hold baseline the other two bots are
measured against. Everything that is not the strategy choice lives in
bot_runner.py.
"""
from bot_runner import run_bot
from cjtrade.pkgs.strategy.dca import DCA_Monthly

SYMBOL = "0050"

PARAMS = {
    # NT$ per purchase, not a fraction of equity. That is the point of DCA:
    # the instalment is a property of the saver's income, not of how the
    # portfolio has done since the last one, so it must not scale with equity
    # the way calc_qty would make it.
    "dca__amount": 10_000.0,
}


if __name__ == "__main__":
    run_bot(DCA_Monthly(), SYMBOL, PARAMS)
