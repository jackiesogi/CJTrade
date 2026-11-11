"""
poc/trading_engine/bot_custom.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs a hand-written strategy file.

    python bot_custom.py <bot_id> <balance> <session_id> <symbol> <path.py>

The file is what a user wrote in FinHub's editor: `on_bar(bar, account)` plus
optional `init`, `on_fill` and `on_end`, written against
cjtrade.pkgs.strategy.authoring. Everything between that and the engine is
user_strategy.UserStrategy; everything below the strategy is bot_runner, the
same as bot_a/bot_b/bot_c.

This process is the one place a user's code executes. It holds no broker
session -- the authoring module cannot reach one, and master's
ExecutionEngine is still the only thing that places an order -- so a strategy
that misbehaves can waste its own risk budget and nothing else.

A bad file ends the process here, before any bar is served, rather than at the
bar it first runs on. The engine reports a bot that exited at startup; a
strategy that raises later is caught per bar by UserStrategy and reported in
its monitors instead.
"""
import logging
import sys
from pathlib import Path

from bot_runner import bot_argv
from bot_runner import run_bot
from cjtrade.pkgs.strategy.user_strategy import load
from cjtrade.pkgs.strategy.user_strategy import StrategyError

log = logging.getLogger("poc.bot_custom")

SYMBOL = "2317"          # only used when master names no symbol


def main() -> int:
    bot_id, _balance, _session, symbol = bot_argv(SYMBOL)
    if len(sys.argv) <= 5 or not sys.argv[5]:
        log.error(f"[{bot_id}] no strategy file given — "
                  f"usage: bot_custom.py <bot_id> <balance> <session> "
                  f"<symbol> <path.py>")
        return 2

    path = Path(sys.argv[5])
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error(f"[{bot_id}] cannot read {path}: {exc}")
        return 2

    try:
        strategy = load(source)
    except StrategyError as exc:
        where = f" (line {exc.line})" if exc.line else ""
        log.error(f"[{bot_id}] {path.name} cannot run{where}: {exc.message}")
        return 2

    strategy.name = path.stem
    # Position sizing for `buy()` with no size. The strategy's own params are
    # declared inside the file and read by the module itself, so the only
    # thing that has to be passed in is the one value that is risk policy
    # rather than strategy -- see UserStrategy._size.
    run_bot(strategy, symbol, {"risk__max_position_pct": 0.20})
    return 0


if __name__ == "__main__":
    sys.exit(main())
