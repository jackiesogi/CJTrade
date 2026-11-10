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
    gate.record_submitted("Bot_C", "BUY", 4_800.0)
    ...
    gate.record_outcome("Bot_C", "BUY", 4_800.0, filled=False, resolved=True)
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict
from typing import Optional
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
    """

    def __init__(self, limits: RiskLimits, initial_equity: float) -> None:
        self.limits = limits
        self.initial_equity = float(initial_equity)
        self._bar = 0
        self._halt_reason: Optional[str] = None
        # Notional each bot currently has deployed. Tracked here because the
        # broker reports positions for the whole account, so master is the only
        # thing that can attribute them to a strategy.
        self._exposure: Dict[str, float] = defaultdict(float)
        self._orders_this_bar: Dict[str, int] = defaultdict(int)
        self._seen: Dict[Tuple, int] = {}      # fingerprint -> bar last seen

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def halted(self) -> bool:
        return self._halt_reason is not None

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    def exposure(self, bot_id: str) -> float:
        return self._exposure[bot_id]

    @property
    def exposures(self) -> Dict[str, float]:
        """Every bot's deployed notional, as a copy.

        Here because ``exposure()`` indexes a defaultdict, so asking about a
        bot that has not traded yet inserts a key. Harmless to the arithmetic,
        but it means a read-only caller -- a status endpoint, a log line --
        cannot look without writing, on an object documented above as not
        thread-safe.
        """
        return dict(self._exposure)

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
            projected = self._exposure[bot_id] + notional
            if projected > lim.max_notional_per_bot:
                return (f"{bot_id} would hold {projected:,.0f} of its "
                        f"{lim.max_notional_per_bot:,.0f} allocation")

        return None

    # ── bookkeeping ───────────────────────────────────────────────────────────

    def record_submitted(self, bot_id: str, symbol: str, action: str,
                         quantity: int, price: float) -> None:
        """An order the broker accepted. Call only after check() allowed it."""
        self._orders_this_bar[bot_id] += 1
        if self.limits.duplicate_window_bars:
            self._seen[self._fingerprint(bot_id, symbol, action, quantity, price)] = self._bar
        if action == "BUY":
            # A resting buy already commits the capital, so it counts from
            # submission -- not from the fill, which is too late to refuse the
            # next order.
            self._exposure[bot_id] += price * quantity

    def record_outcome(self, bot_id: str, action: str, notional: float,
                       filled: bool) -> None:
        """An order reached a terminal state.

        A buy that died releases its capital; a buy that filled keeps it (the
        notional just moved from resting to held). A sell releases capital when
        it fills, and changes nothing when it dies.
        """
        if action == "BUY" and not filled:
            self._exposure[bot_id] -= notional
        elif action == "SELL" and filled:
            self._exposure[bot_id] -= notional
        # Exposure is a notional estimate, not a mark-to-market, so rounding
        # drift across many fills could otherwise leave a bot permanently
        # unable to trade.
        if abs(self._exposure[bot_id]) < 1e-6:
            self._exposure[bot_id] = 0.0

    @staticmethod
    def _fingerprint(bot_id: str, symbol: str, action: str,
                     quantity: int, price: float) -> Tuple:
        return (bot_id, symbol, action, int(quantity), round(float(price), 4))
