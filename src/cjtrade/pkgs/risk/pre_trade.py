"""Pre-trade risk controls.

Separate from a broker's own checks, and not a replacement for them. A broker
answers "can this account do this at all" -- buying power, available-to-sell,
price bands. This answers "should this strategy do this now" -- its capital
allocation, its order rate, whether trading has been halted. No real broker
will enforce your per-strategy budget.

Every control is off by default (None), so a caller opts into exactly what it
wants and the gate never silently changes behaviour it was not asked about.

Usage::

    from cjtrade.pkgs.risk import RiskGate, RiskLimits

    gate = RiskGate(RiskLimits(max_notional_per_bot=500_000,
                               max_orders_per_bar=5,
                               max_loss_pct=0.10),
                    initial_equity=1_000_000)

    gate.start_bar(bar_index)
    if gate.observe_equity(equity):        # kill switch tripped
        ...                                # cancel resting orders, stop trading

    reason = gate.check("Bot_C", "2317", "BUY", 20, 240.0)
    if reason:
        ...                                # refuse, do not reach the broker
    gate.record_submitted("Bot_C", "2317", "BUY", 20, 240.0, order_id=oid)
    ...
    gate.record_outcome(oid, filled=False)      # cancelled: capital released
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple


@dataclass(frozen=True)
class RiskLimits:
    """Which controls are on. None disables that one.

    Attributes
    ----------
    max_notional_per_bot : float, optional
        Capital a single strategy may have deployed at once: resting buys plus
        the notional it has actually bought. This is what keeps N strategies on
        one account from each sizing against the full equity.
    max_orders_per_bar : int, optional
        Runaway protection. A strategy that re-fires every bar is a bug, and
        without this the broker absorbs it as a reject storm.
    max_loss_pct : float, optional
        Kill switch. Equity below ``initial * (1 - max_loss_pct)`` halts all
        new orders.
    duplicate_window_bars : int
        An identical (bot, symbol, action, quantity, price) within this many
        bars is refused. 0 disables it.
    """
    max_notional_per_bot: Optional[float] = None
    max_orders_per_bar: Optional[int] = None
    max_loss_pct: Optional[float] = None
    duplicate_window_bars: int = 0


class RiskGate:
    """The one place an order can be refused before it reaches the broker.

    Not thread-safe: drive it from the single task that owns execution.

    Parameters
    ----------
    limits : RiskLimits
        Which controls are on.
    initial_equity : float
        Equity the ``max_loss_pct`` kill switch is measured against.
    """

    def __init__(self, limits: RiskLimits, initial_equity: float) -> None:
        self.limits = limits
        self.initial_equity = float(initial_equity)
        self._bar = 0
        self._halt_reason: Optional[str] = None
        # What each bot has deployed, tracked here because the broker reports
        # positions for the whole account, so master is the only thing that
        # can attribute them to a strategy. Two parts:
        #   resting  order id -> (bot, symbol, action, quantity, price), for
        #            every accepted order not yet resolved. Keyed by order so a
        #            second outcome for the same order, or an outcome for an
        #            order the gate never recorded, cannot move the numbers.
        #   held     (bot, symbol) -> [shares, cost], the cost basis of what
        #            the bot's filled buys still hold. A sell retires cost at
        #            the average, never at the sale price, so a profitable
        #            sell cannot push exposure below zero.
        self._resting: Dict[str, Tuple[str, str, str, int, float]] = {}
        self._held: Dict[Tuple[str, str], List[float]] = {}
        self._bots: Set[str] = set()
        self._orders_this_bar: Dict[str, int] = defaultdict(int)
        self._seen: Dict[Tuple, int] = {}      # fingerprint -> bar last seen

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def halted(self) -> bool:
        """True once trading has been halted."""
        return self._halt_reason is not None

    @property
    def halt_reason(self) -> Optional[str]:
        """Why trading was halted, or None."""
        return self._halt_reason

    def exposure(self, bot_id: str) -> float:
        """Capital the bot has committed: resting buys plus held cost basis."""
        resting = sum(q * p for b, _s, a, q, p in self._resting.values()
                      if b == bot_id and a == "BUY")
        held = sum(cost for (b, _s), (_sh, cost) in self._held.items()
                   if b == bot_id)
        total = resting + held
        # Rounding drift across many fills must not strand a bot just above
        # its limit, or leave a ghost exposure once everything is closed.
        return 0.0 if abs(total) < 1e-6 else total

    @property
    def exposures(self) -> Dict[str, float]:
        """Every bot that has had an order accepted, with its exposure.

        Read-only: asking does not register a bot, so a status endpoint or a
        log line can look without writing, on an object documented above as
        not thread-safe.
        """
        return {b: self.exposure(b) for b in sorted(self._bots)}

    def start_bar(self, bar_index: int) -> None:
        """Reset per-bar counters. Call once per bar before any check()."""
        self._bar = bar_index
        self._orders_this_bar.clear()
        if self.limits.duplicate_window_bars:
            cutoff = bar_index - self.limits.duplicate_window_bars
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

    def observe_equity(self, equity: float) -> Optional[str]:
        """Kill switch. Returns the halt reason the first time it trips.

        Returns None once already halted, so a caller can use a truthy return
        as "halt right now" without re-running its shutdown every bar.
        """
        if self.halted or self.limits.max_loss_pct is None:
            return None
        floor = self.initial_equity * (1.0 - self.limits.max_loss_pct)
        if equity < floor:
            self._halt_reason = (
                f"equity {equity:,.0f} fell below the "
                f"{self.limits.max_loss_pct:.0%} loss limit "
                f"({floor:,.0f} of {self.initial_equity:,.0f})"
            )
            return self._halt_reason
        return None

    def halt(self, reason: str) -> None:
        """Trip the kill switch by hand."""
        if not self.halted:
            self._halt_reason = reason

    # ── the gate ──────────────────────────────────────────────────────────────

    def check(self, bot_id: str, symbol: str, action: str,
              quantity: int, price: float) -> Optional[str]:
        """Rejection reason, or None to let the order through.

        Checked in order of how cheap the refusal is: a halted engine refuses
        everything, then the rate limit, then the duplicate, then the budget.
        """
        if self.halted:
            return f"trading halted: {self._halt_reason}"

        lim = self.limits
        if lim.max_orders_per_bar is not None:
            if self._orders_this_bar[bot_id] >= lim.max_orders_per_bar:
                return (f"{bot_id} already sent {lim.max_orders_per_bar} order(s) "
                        f"this bar")

        if lim.duplicate_window_bars:
            fp = self._fingerprint(bot_id, symbol, action, quantity, price)
            last = self._seen.get(fp)
            if last is not None and self._bar - last < lim.duplicate_window_bars:
                return (f"duplicate of an order {self._bar - last} bar(s) ago "
                        f"({action} {symbol} x{quantity} @ {price})")

        if lim.max_notional_per_bot is not None and action == "BUY":
            notional = price * quantity
            projected = self.exposure(bot_id) + notional
            if projected > lim.max_notional_per_bot:
                return (f"{bot_id} would hold {projected:,.0f} of its "
                        f"{lim.max_notional_per_bot:,.0f} allocation")

        return None

    # ── bookkeeping ───────────────────────────────────────────────────────────

    def record_submitted(self, bot_id: str, symbol: str, action: str,
                         quantity: int, price: float,
                         order_id: Optional[str] = None) -> None:
        """An order the broker accepted. Call only after check() allowed it.

        With an ``order_id`` the order counts against the bot's allocation
        until record_outcome() resolves it. A resting buy commits the capital
        from submission, not from the fill, which is too late to refuse the
        next order. Without one, only the rate and duplicate checks see it.
        """
        self._orders_this_bar[bot_id] += 1
        self._bots.add(bot_id)
        if self.limits.duplicate_window_bars:
            self._seen[self._fingerprint(bot_id, symbol, action, quantity, price)] = self._bar
        if order_id is not None:
            self._resting[order_id] = (bot_id, symbol, action,
                                       int(quantity), float(price))

    def record_outcome(self, order_id: str, filled: bool) -> None:
        """An order reached a terminal state, filled in full or not at all.

        An order the gate is not holding is ignored: one the broker rejected
        on placement was never recorded, and an order resolved twice (a cancel
        racing a fill) must only count once.
        """
        entry = self._resting.pop(order_id, None)
        if entry is None or not filled:
            return
        bot_id, symbol, action, quantity, price = entry
        lot = self._held.setdefault((bot_id, symbol), [0.0, 0.0])
        if action == "BUY":
            lot[0] += quantity
            lot[1] += quantity * price
            return
        # A sell of shares this gate never saw bought (a position that
        # predates the run) has no cost basis here to retire.
        sold = min(float(quantity), lot[0])
        if sold <= 0:
            return
        lot[1] -= lot[1] * (sold / lot[0])
        lot[0] -= sold
        if lot[0] <= 0 or abs(lot[1]) < 1e-6:
            del self._held[(bot_id, symbol)]

    @staticmethod
    def _fingerprint(bot_id: str, symbol: str, action: str,
                     quantity: int, price: float) -> Tuple:
        return (bot_id, symbol, action, int(quantity), round(float(price), 4))
