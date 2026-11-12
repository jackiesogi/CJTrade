"""
pkgs/strategy/dca.py
~~~~~~~~~~~~~~~~~~~~~
Monthly dollar-cost averaging.

Behavior
--------
- Buys a fixed NT$ amount of each symbol it sees, once per calendar month, on
  the first bar of that month this strategy is given.
- Never sells. This is the accumulate-and-hold baseline, so there is no exit.

Why calendar months and not "30 days since the last buy"
--------------------------------------------------------
This used to wait `timedelta(days=30)`, which drifts: buy on 5 January and the
next purchase is 4 February, then 6 March, and by December the instalment has
slid a week and a half earlier. Over a multi-year backtest that silently
changes how many instalments fit in the run -- 12.2 a year rather than 12 --
and the comparison against a real monthly savings plan stops holding.

"The first bar of the month" also needs no trading calendar. The month rolls
over on whatever bar arrives first, so a 1st that is a Sunday, a holiday or a
typhoon day resolves itself: the bot buys on the first bar it is actually given
in the new month. The alternative -- "buy on the 1st, or the next trading day
if the 1st is closed" -- would need holiday data this codebase does not have
(TradingCalendar.is_trading_day is weekday-only; see trading_calendar.py).

Usage
-----
    from cjtrade.pkgs.strategy.dca import DCA_Monthly
    strategy = DCA_Monthly(amount=10_000)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)

# NT$ per instalment, when nothing else says otherwise.
DCA_MONTHLY_AMOUNT = 10_000.0


class DCA_Monthly(BaseStrategy):
    """Buy a fixed amount of each symbol, once per calendar month.

    Parameters (constructor, or via ctx.params in on_start)
    - dca__amount: NT$ to spend per instalment, per symbol.
    - dca__last_buy_time: optional {symbol: ISO timestamp} of the last purchase
      made before this run, so a resumed run does not buy twice in one month.
    """

    name = "DCA"
    long_name = "DCA_Monthly"

    def __init__(self, amount: float = DCA_MONTHLY_AMOUNT) -> None:
        self._amount = float(amount)
        # The (year, month) each symbol was last bought in. A month rather than
        # a timestamp because that is the whole of the decision: comparing
        # months cannot drift, and two bars in the same month are the same
        # answer however far apart they are.
        self._last_buy_month: Dict[str, Tuple[int, int]] = {}
        self._last_buy_at: Dict[str, datetime] = {}

        # ── monitor state ────────────────────────────────────────────────────
        self._n_bars = 0
        self._n_signals = 0
        self._shares = 0
        self._deployed = 0.0
        # (symbol, year, month) already reported as unaffordable, so the
        # warning is one line per month rather than one per bar.
        self._unaffordable: set[Tuple[str, int, int]] = set()
        self._last_reason = "not started"

    def on_start(self, ctx: StrategyContext) -> None:
        p = ctx.params
        # Support the older spellings so an existing config keeps working.
        self._amount = float(p.get("dca__amount",
                                   p.get("dca_amount", self._amount)))

        seed = p.get("dca__last_buy_time", p.get("dca_last_buy_time"))
        if isinstance(seed, dict):
            for sym, iso in seed.items():
                try:
                    when = datetime.fromisoformat(iso)
                except (TypeError, ValueError):
                    log.warning("[%s] ignoring unparseable last_buy_time for "
                                "%s: %r", self.name, sym, iso)
                    continue
                self._last_buy_at[sym] = when
                self._last_buy_month[sym] = (when.year, when.month)

        self._last_reason = "no bars yet"
        log.info(f"[{self.name}] amount={self._amount:,.0f} per month per symbol")

    # ── monitoring ───────────────────────────────────────────────────────────

    def plots(self) -> Dict[str, float]:
        """The running average cost, which is the only line this strategy has.

        A DCA chart's whole question is where the average sits against the
        price, so that is what gets drawn. Nothing until the first purchase,
        because an average of no purchases is not zero -- it does not exist.
        """
        if not self._shares:
            return {}
        return {"avg_cost": self._deployed / self._shares}

    def monitors(self) -> Dict[str, Any]:
        """See BaseStrategy.monitors. Plain floats, ints and strings only."""
        last = max(self._last_buy_at.values()) if self._last_buy_at else None
        return {
            "bars_seen":        self._n_bars,
            "amount":           round(self._amount, 2),
            "instalments":      self._n_signals,
            "shares_bought":    self._shares,
            "cash_deployed":    round(self._deployed, 2),
            "avg_cost":         round(self._deployed / self._shares, 2) if self._shares else 0.0,
            "last_buy":         last.isoformat(sep=" ", timespec="minutes") if last else "never",
            # Months skipped because one share cost more than the instalment.
            # Separated from the normal "already bought" case because it is the
            # only way this strategy silently does nothing for a whole month.
            "months_unaffordable": len(self._unaffordable),
            "signals_emitted":  self._n_signals,
            "last_decision":    self._last_reason,
        }

    # ── strategy ─────────────────────────────────────────────────────────────

    def on_bar(self, bar, ctx: StrategyContext) -> List[Signal]:
        self._n_bars += 1

        now: datetime = ctx.timestamp
        sym = bar.symbol
        price = bar.close
        this_month = (now.year, now.month)

        if self._last_buy_month.get(sym) == this_month:
            self._last_reason = (f"already bought {sym} in "
                                 f"{now.year}-{now.month:02d}")
            return []

        if price <= 0:
            self._last_reason = f"no usable price for {sym} ({price})"
            return []

        # Whole shares of a fixed sum, so the instalment is at most `amount`
        # and the remainder is simply not spent. Odd lots, which is what the
        # engine submits anyway (bot_runner's OrderLot.IntraDayOdd).
        qty = int(self._amount // price)
        if qty <= 0:
            # One share costs more than a whole instalment. Reported rather
            # than retried silently: nothing will change within the month, and
            # the month is deliberately NOT consumed, so a later bar at a lower
            # price can still buy.
            marker = (sym, now.year, now.month)
            if marker not in self._unaffordable:
                self._unaffordable.add(marker)
                log.warning(f"[{self.name}] {sym} at {price:.2f} costs more "
                            f"than one instalment of {self._amount:,.0f} — "
                            f"skipping {now.year}-{now.month:02d} unless it "
                            f"falls before the month is out")
            self._last_reason = (f"unaffordable: one share of {sym} at "
                                 f"{price:.2f} exceeds {self._amount:,.0f}")
            return []

        # Consume the month when the signal is ISSUED, not when it fills.
        #
        # The trade-off is deliberate and it cuts both ways: a rejected or
        # never-filled order means this month's instalment is lost, but marking
        # it on the fill instead would re-signal on every bar until one fills,
        # and a limit order that is merely resting would collect a dozen
        # duplicates before the first one settles.
        self._last_buy_month[sym] = this_month
        self._last_buy_at[sym] = now
        self._n_signals += 1
        self._shares += qty
        self._deployed += qty * price

        self._last_reason = (f"BUY {qty} {sym} @ {price:.2f} — instalment for "
                             f"{now.year}-{now.month:02d}")
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"ts: {ts_str} | BUY {sym} @ {price:.2f} * {qty} shares "
                 f"(DCA {now.year}-{now.month:02d})")
        return [Signal(
            action="BUY", symbol=sym, quantity=qty, price=price,
            reason=f"DCA instalment for {now.year}-{now.month:02d}",
            meta={"amount": self._amount, "month": f"{now.year}-{now.month:02d}"},
        )]

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        if fill.action.upper() == "BUY":
            log.debug(f"[{self.name}] BUY filled for {fill.symbol} "
                      f"@ {fill.price:.2f}")

    def last_buy(self, symbol: str) -> Optional[datetime]:
        """When this strategy last bought `symbol`, or None.

        Exposed so a caller can hand it back as dca__last_buy_time and resume
        without buying twice in the same month.
        """
        return self._last_buy_at.get(symbol)
